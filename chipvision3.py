#!/usr/bin/env python3
import sys
sys.path.insert(0, "/home/scalepi/hailo-rpi5-examples/basic_pipelines")

import os
import subprocess
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import numpy as np
import cv2
import hailo
from hailo_rpi_common import get_caps_from_pad, app_callback_class
from detection_pipeline import GStreamerDetectionApp

# --- Motor GPIO Setup ---
import gpiod
MOTOR_PIN = 24
_chip = gpiod.Chip('gpiochip0')
_motor_line = _chip.get_line(MOTOR_PIN)
_motor_line.request(consumer="motor", type=gpiod.LINE_REQ_DIR_OUT)

def start_motor():
    try:
        _motor_line.set_value(1)
        print("✅ Motor started.")
    except Exception as e:
        print(f"⚠️ Failed to start motor: {e}")

def stop_motor():
    try:
        _motor_line.set_value(0)
        print("✅ Motor stopped.")
    except Exception as e:
        print(f"⚠️ Failed to stop motor: {e}")

# --- Configuration ---
HAILO_ENV_SCRIPT = "/home/scalepi/hailo-rpi5-examples/setup_env.sh"
HAILO_VENV_PATH  = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi5_examples/bin/activate"
SAVE_FOLDER      = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE   = os.path.join(SAVE_FOLDER, "latest_detection.txt")

# Two-frame support (no pipeline restart)
MULTI_CAPTURE_FLAG = os.path.join(SAVE_FOLDER, "multi_capture.flag")

# EXACT timing per your clarification:
PAUSE_SEC = 1.0     # pause after Frame 1
NUDGE_SEC = 1.5     # motor run between Frame 1 and Frame 2

# --- Environment Activation Function ---
def activate_hailo_env():
    if os.getenv("HAILO_ENV_ACTIVATED") == "1":
        return
    cmd = (
        f"bash -c 'source {HAILO_ENV_SCRIPT} && "
        f"source {HAILO_VENV_PATH} && "
        f"export HAILO_ENV_ACTIVATED=1 && env'"
    )
    r = subprocess.run(cmd, shell=True, executable="/bin/bash",
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ Error activating environment:", r.stderr)
        sys.exit(1)
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        os.environ[k] = v
    os.environ.setdefault("TAPPAS_POST_PROC_DIR",
        "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes")

# --- Change Working Directory ---
os.chdir("/home/scalepi/hailo-rpi5-examples")

# --- Callback Class for Detection ---
class UserAppCallback(app_callback_class):
    def __init__(self, pipeline, main_loop):
        super().__init__()
        self.pipeline = pipeline
        self.main_loop = main_loop
        # state for 2-frame flow
        self.have_frame1  = False
        self.need_frame2  = False
        self.ready_frame2 = False   # set True after pause + nudge complete
        self.did_frame2   = False
        self.stop_detection = False # detach pad probe when done

# --- Extract Raw Frame Utility ---
def extract_raw_frame(buffer, width, height):
    ok, mi = buffer.map(Gst.MapFlags.READ)
    if not ok:
        return None
    try:
        arr = np.frombuffer(mi.data, dtype=np.uint8)
        return arr.reshape((height, width, 3))
    finally:
        buffer.unmap(mi)

# --- Save Full Frame + Crop Indexed ---
def save_full_and_crop(frame, bbox, idx, suffix=""):
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    full_path = os.path.join(SAVE_FOLDER, f"chip{suffix}.png")
    cv2.imwrite(full_path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    x1, y1, x2, y2 = bbox
    h, w, _ = frame.shape
    if x2 <= 1.0 and y2 <= 1.0:
        xi1, yi1 = int(x1 * w), int(y1 * h)
        xi2, yi2 = int(x2 * w), int(y2 * h)
    else:
        xi1, yi1, xi2, yi2 = map(int, (x1, y1, x2, y2))
    xi1, yi1 = max(0, xi1), max(0, yi1)
    xi2, yi2 = min(w, xi2), min(h, yi2)

    cropped_path = (os.path.join(SAVE_FOLDER, f"chip_cropped_{suffix}_{idx}.png")
                    if suffix else os.path.join(SAVE_FOLDER, f"chip_cropped_{idx}.png"))
    crop = cv2.cvtColor(frame[yi1:yi2, xi1:xi2], cv2.COLOR_RGB2BGR)
    cv2.imwrite(cropped_path, crop)
    return full_path, cropped_path

# --- Stop pipeline and quit main loop (run on main thread) ---
def _stop_and_quit_async(user_data: UserAppCallback):
    try:
        user_data.pipeline.set_state(Gst.State.NULL)
    except Exception as e:
        print(f"⚠️ set_state(NULL) error: {e}")
    try:
        if user_data.main_loop:
            user_data.main_loop.quit()
    except Exception as e:
        print(f"⚠️ main_loop.quit() error: {e}")
    return False  # run once

# --- Schedule: 1s pause, then 1.5s nudge, then mark ready for Frame 2 ---
def _schedule_pause_then_nudge(user_data: UserAppCallback):
    def _start_nudge():
        print(f"🔵 Large-parts: starting {NUDGE_SEC:.1f}s belt nudge…")
        start_motor()
        def _stop_and_ready():
            stop_motor()
            user_data.ready_frame2 = True
            print("🟢 Ready for Frame 2 capture (no Y-threshold).")
            return False
        GLib.timeout_add(int(NUDGE_SEC * 1000), _stop_and_ready)
        return False

    print(f"⏸️ Pausing {PAUSE_SEC:.1f}s before nudge…")
    GLib.timeout_add(int(PAUSE_SEC * 1000), _start_nudge)
    return False

# --- GStreamer Pad Callback ---
def app_callback(pad, info, user_data: UserAppCallback):
    buf = info.get_buffer()
    if not buf or user_data.stop_detection:
        return Gst.PadProbeReturn.REMOVE if user_data.stop_detection else Gst.PadProbeReturn.OK

    fmt, w, h = get_caps_from_pad(pad)
    if not (fmt and w and h):
        return Gst.PadProbeReturn.OK

    frame = extract_raw_frame(buf, w, h)
    if frame is None:
        return Gst.PadProbeReturn.OK

    detections = hailo.get_roi_from_buffer(buf).get_objects_typed(hailo.HAILO_DETECTION)

    crop_list = []
    for det in detections:
        label      = det.get_label()
        bbox       = det.get_bbox()
        confidence = det.get_confidence()
        x1, y1     = bbox.xmin(), bbox.ymin()
        x2, y2     = bbox.xmax(), bbox.ymax()
        print(f"Detection - Label: {label}, "
              f"BBox: ({x1:.2f}, {y1:.2f}) -> ({x2:.2f}, {y2:.2f}), "
              f"Confidence: {confidence:.2f}")
        crop_list.append((x1, y1, x2, y2))

    # ---------- Frame 1: stop when y1 > 0.4 ----------
    if not user_data.have_frame1:
        trigger_stop = any(y1 > 0.4 for (_, y1, _, _) in crop_list)
        if trigger_stop:
            stop_motor()
            user_data.have_frame1 = True

            with open(DETECTION_FILE, "w") as f:
                f.write("FRAME=1\n")
                if not crop_list:
                    full_path = os.path.join(SAVE_FOLDER, "chip.png")
                    cv2.imwrite(full_path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                    f.write("No detections found\n\n")
                else:
                    for i, (x1, y1, x2, y2) in enumerate(crop_list, start=1):
                        print(f"Saving Crop {i} (Frame 1)")
                        full, crop = save_full_and_crop(frame, (x1, y1, x2, y2), i, suffix="")
                        f.write(f"Cropped Photo Location: {full},{crop}\n")
                        f.write(f"Coordinates of the Detection Box: ({x1}, {y1}) -> ({x2}, {y2})\n\n")

            if os.path.exists(MULTI_CAPTURE_FLAG):
                user_data.need_frame2  = True
                user_data.ready_frame2 = False
                GLib.idle_add(_schedule_pause_then_nudge, user_data)
            else:
                # Done after frame 1 (Large Parts OFF): close pipeline & quit
                user_data.stop_detection = True
                GLib.idle_add(_stop_and_quit_async, user_data)
                return Gst.PadProbeReturn.REMOVE

            return Gst.PadProbeReturn.OK

        # Not triggered yet; keep streaming
        return Gst.PadProbeReturn.OK

    # ---------- Frame 2: IGNORE Y, capture first buffer after pause+nudge ----------
    if user_data.need_frame2 and user_data.ready_frame2 and not user_data.did_frame2:
        user_data.did_frame2 = True

        with open(DETECTION_FILE, "a") as f:
            f.write("FRAME=2\n")
            if not crop_list:
                print("ℹ️ Frame 2: No detections found; saving full frame only.")
                full_path = os.path.join(SAVE_FOLDER, "chip2.png")
                cv2.imwrite(full_path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                f.write("No detections found\n\n")
            else:
                for i, (x1, y1, x2, y2) in enumerate(crop_list, start=1):
                    print(f"Saving Crop {i} (Frame 2)")
                    full, crop = save_full_and_crop(frame, (x1, y1, x2, y2), i, suffix="2")
                    f.write(f"Cropped Photo Location: {full},{crop}\n")
                    f.write(f"Coordinates of the Detection Box: ({x1}, {y1}) -> ({x2}, {y2})\n\n")

        # Finalize after frame 2: close pipeline & quit
        user_data.stop_detection = True
        GLib.idle_add(_stop_and_quit_async, user_data)
        return Gst.PadProbeReturn.REMOVE

    # Otherwise keep streaming
    return Gst.PadProbeReturn.OK

# --- Main Execution ---
def stop_pipeline_safe(pipeline, main_loop):
    # Extra safety in case we didn't stop above for any reason
    try:
        pipeline.set_state(Gst.State.NULL)
    except Exception as e:
        print(f"⚠️ set_state(NULL) error: {e}")
    try:
        if main_loop:
            main_loop.quit()
    except Exception as e:
        print(f"⚠️ main_loop.quit() error: {e}")

if __name__ == "__main__":
    activate_hailo_env()
    Gst.init(None)

    main_loop = GLib.MainLoop()
    dummy = Gst.Pipeline.new("dummy-pipeline")
    user_data = UserAppCallback(dummy, main_loop)
    app = GStreamerDetectionApp(app_callback, user_data)
    user_data.pipeline = app.pipeline

    try:
        start_motor()
        print(">>> Running chip detection pipeline...")
        app.run()
        main_loop.run()
    except Exception as e:
        print(f"Application terminated: {e}")
    finally:
        stop_motor()
        stop_pipeline_safe(user_data.pipeline, user_data.main_loop)
