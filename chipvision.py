#!/usr/bin/env python3
import sys
sys.path.insert(0, "/home/scalepi/hailo-rpi5-examples/basic_pipelines")

import os
import subprocess
import time
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import numpy as np
import cv2
import hailo
from datetime import datetime
from hailo_rpi_common import get_caps_from_pad, app_callback_class
from detection_pipeline import GStreamerDetectionApp

# --- Configuration ---
# Environment activation paths
HAILO_ENV_SCRIPT = "/home/scalepi/hailo-rpi5-examples/setup_env.sh"
HAILO_VENV_PATH = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi5_examples/bin/activate"
# Folder where images will be saved and detection file
SAVE_FOLDER = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE = "/home/scalepi/Desktop/savephototest/latest_detection.txt"


# --- Environment Activation Function ---
def activate_hailo_env():
    if os.getenv("HAILO_ENV_ACTIVATED") == "1":
        print("✅ Hailo environment is already active.")
        return
    print("🔧 Activating Hailo Environment...")
    command = (
        f"bash -c 'source {HAILO_ENV_SCRIPT} && "
        f"source {HAILO_VENV_PATH} && "
        f"export HAILO_ENV_ACTIVATED=1 && env'"
    )
    result = subprocess.run(command, shell=True, executable="/bin/bash", capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ Error activating environment:", result.stderr)
        sys.exit(1)
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        os.environ[key] = value
    if "TAPPAS_POST_PROC_DIR" not in os.environ:
        os.environ["TAPPAS_POST_PROC_DIR"] = "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes"
    print("✅ Hailo environment activated successfully.")

# --- (Optional) Change Working Directory ---
# Ensure that relative paths (like for the HEF file) work correctly.
os.chdir("/home/scalepi/hailo-rpi5-examples")
print("Current working directory:", os.getcwd())

# --- Callback Class for Detection ---
class UserAppCallback(app_callback_class):
    def __init__(self, pipeline, main_loop):
        super().__init__()
        self.stop_detection = False
        self.pipeline = pipeline
        self.main_loop = main_loop

# --- Utility: Extract Raw Frame from Buffer ---import os import subprocess import time import gi gi.require_version('Gst', '1.0') from gi.repository import Gst, GLib import numpy as np import cv2 import hailo from hailo_rpi_common import get_caps_from_pad, app_callback_class from detection_pipeline import GStreamerDetectionApp # --- Motor GPIO Setup --- import gpiod MOTOR_PIN = 24 _chip = gpiod.Chip('gpiochip0') _motor_line = _chip.get_line(MOTOR_PIN) _motor_line.request(consumer="motor", type=gpiod.LINE_REQ_DIR_OUT) def start_motor(): try: _motor_line.set_value(1) print("✅ Motor started.") except Exception as e: print(f"⚠️ Failed to start motor: {e}") def stop_motor(): try: _motor_line.set_value(0) print("✅ Motor stopped.") except Exception as e: print(f"⚠️ Failed to stop motor: {e}") # --- Configuration --- HAILO_ENV_SCRIPT = "/home/scalepi/hailo-rpi5-examples/setup_env.sh" HAILO_VENV_PATH = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi5_examples/bin/activate" SAVE_FOLDER = "/home/scalepi/Desktop/savephototest" DETECTION_FILE = "/home/scalepi/Desktop/savephototest/latest_detection.txt" # --- Environment Activation Function --- def activate_hailo_env(): if os.getenv("HAILO_ENV_ACTIVATED") == "1": return cmd = ( f"bash -c 'source {HAILO_ENV_SCRIPT} && " f"source {HAILO_VENV_PATH} && " f"export HAILO_ENV_ACTIVATED=1 && env'" ) r = subprocess.run(cmd, shell=True, executable="/bin/bash", capture_output=True, text=True) if r.returncode != 0: print("❌ Error activating environment:", r.stderr) sys.exit(1) for line in r.stdout.splitlines(): k, _, v = line.partition("=") os.environ[k] = v os.environ.setdefault("TAPPAS_POST_PROC_DIR", "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes") # --- Change Working Directory --- os.chdir("/home/scalepi/hailo-rpi5-examples") # --- Callback Class for Detection --- class UserAppCallback(app_callback_class): def __init__(self, pipeline, main_loop): super().__init__() self.stop_detection = False self.pipeline = pipeline self.main_loop = main_loop # --- Extract Raw Frame Utility --- def extract_raw_frame(buffer, width, height): ok, mi = buffer.map(Gst.MapFlags.READ) if not ok: return None try: arr = np.frombuffer(mi.data, dtype=np.uint8) return arr.reshape((height, width, 3)) finally: buffer.unmap(mi) # --- Save Full Frame + Crop Indexed --- def save_full_and_crop(frame, bbox, idx): os.makedirs(SAVE_FOLDER, exist_ok=True) # save full image once full_path = os.path.join(SAVE_FOLDER, "chip.png") cv2.imwrite(full_path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)) # crop per chip x1, y1, x2, y2 = bbox h, w, _ = frame.shape if x2 <= 1.0 and y2 <= 1.0: xi1, yi1 = int(x1 * w), int(y1 * h) xi2, yi2 = int(x2 * w), int(y2 * h) else: xi1, yi1, xi2, yi2 = map(int, (x1, y1, x2, y2)) xi1, yi1 = max(0, xi1), max(0, yi1) xi2, yi2 = min(w, xi2), min(h, yi2) cropped_path = os.path.join(SAVE_FOLDER, f"chip_cropped_{idx}.png") crop = cv2.cvtColor(frame[yi1:yi2, xi1:xi2], cv2.COLOR_RGB2BGR) cv2.imwrite(cropped_path, crop) return full_path, cropped_path # --- Stop Pipeline Utility --- def stop_pipeline(pipeline, main_loop): try: pipeline.set_state(Gst.State.NULL) except: pass try: Gst.deinit() except: pass if main_loop: main_loop.quit() os._exit(0) # --- GStreamer Pad Callback --- # --- inside your script, replace the old app_callback with this one --- def app_callback(pad, info, user_data): buf = info.get_buffer() # if we've already triggered, bail out if not buf or user_data.stop_detection: return Gst.PadProbeReturn.DROP if user_data.stop_detection else Gst.PadProbeReturn.OK # get frame dimensions fmt, w, h = get_caps_from_pad(pad) if not (fmt and w and h): return Gst.PadProbeReturn.OK # extract the numpy frame frame = extract_raw_frame(buf, w, h) if frame is None: return Gst.PadProbeReturn.OK # pull all detections from Hailo detections = hailo.get_roi_from_buffer(buf).get_objects_typed(hailo.HAILO_DETECTION) crop_list = [] trigger_stop = False # 1) Print them and build list of all bboxes for det in detections: label = det.get_label() bbox = det.get_bbox() confidence = det.get_confidence() x1, y1 = bbox.xmin(), bbox.ymin() x2, y2 = bbox.xmax(), bbox.ymax() # print every detection print(f"Detection - Label: {label}, " f"BBox: ({x1:.2f}, {y1:.2f}) -> ({x2:.2f}, {y2:.2f}), " f"Confidence: {confidence:.2f}") # add to the crop list crop_list.append((x1, y1, x2, y2)) # if any crosses y1 > 0.4, we will stop if y1 > 0.4: trigger_stop = True # 2) If we hit the threshold, stop motor & crop **all** printed detections if trigger_stop: stop_motor() user_data.stop_detection = True with open(DETECTION_FILE, "w") as f: for i, (x1, y1, x2, y2) in enumerate(crop_list, start=1): print(f"Saving Crop {i}") full, crop = save_full_and_crop(frame, (x1, y1, x2, y2), i) f.write(f"Cropped Photo Location: {full},{crop}\n") f.write(f"Coordinates of the Detection Box: ({x1}, {y1}) -> ({x2}, {y2})\n\n") # gracefully tear down GLib.idle_add(stop_pipeline, user_data.pipeline, user_data.main_loop) return Gst.PadProbeReturn.OK # --- Main Execution --- if __name__ == "__main__": activate_hailo_env() Gst.init(None) main_loop = GLib.MainLoop() dummy = Gst.Pipeline.new("dummy-pipeline") user_data = UserAppCallback(dummy, main_loop) app = GStreamerDetectionApp(app_callback, user_data) user_data.pipeline = app.pipeline try: start_motor() print(">>> Running chip detection pipeline...") app.run() main_loop.run() except Exception as e: print(f"Application terminated: {e}") finally: stop_motor() stop_pipeline(user_data.pipeline, user_data.main_loop)e ---
def save_frame_and_crop(frame, x_min, y_min, x_max, y_max):
    try:
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if not os.path.exists(SAVE_FOLDER):
            os.makedirs(SAVE_FOLDER)
        # Use fixed filenames
        full_filename = os.path.join(SAVE_FOLDER, "chip.png")
        cropped_filename = os.path.join(SAVE_FOLDER, "chip_cropped.png")
        
        cv2.imwrite(full_filename, frame_bgr)
        print(f"Full frame saved at {full_filename}")
        
        height, width, _ = frame_bgr.shape
        if x_max <= 1.0 and y_max <= 1.0:
            x1 = int(x_min * width)
            y1 = int(y_min * height)
            x2 = int(x_max * width)
            y2 = int(y_max * height)
        else:
            x1, y1, x2, y2 = int(x_min), int(y_min), int(x_max), int(y_max)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width, x2), min(height, y2)
        cropped = frame_bgr[y1:y2, x1:x2]
        cv2.imwrite(cropped_filename, cropped)
        print(f"Cropped image saved at {cropped_filename}")
        return full_filename, cropped_filename
    except Exception as e:
        print(f"Error saving images: {e}")
        return "", ""

# --- GStreamer Callback ---
def app_callback(pad, info, user_data):
    if user_data.stop_detection:
        return Gst.PadProbeReturn.DROP

    buffer = info.get_buffer()
    if not buffer:
        return Gst.PadProbeReturn.OK

    fmt, width, height = get_caps_from_pad(pad)
    if not fmt or not width or not height:
        return Gst.PadProbeReturn.OK

    frame = extract_raw_frame(buffer, width, height)
    if frame is None:
        return Gst.PadProbeReturn.OK

    # Use Hailo's API to get detections
    roi = hailo.get_roi_from_buffer(buffer)
    detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    

      
    for detection in detections:
        label = detection.get_label()
        bbox = detection.get_bbox()
        confidence = detection.get_confidence()
        x1, y1, x2, y2 = bbox.xmin(), bbox.ymin(), bbox.xmax(), bbox.ymax()
        print(f"Detection - Label: {label}, BBox: ({x1:.2f}, {y1:.2f}) -> ({x2:.2f}, {y2:.2f}), Confidence: {confidence:.2f}")
        if y1 > 0.4:
            user_data.stop_detection = True
            full_path, cropped_path = save_frame_and_crop(frame, x1, y1, x2, y2)
            with open(DETECTION_FILE, "w") as f:
                f.write(f"Cropped Photo Location: {full_path},{cropped_path}\n")
                f.write(f"Coordinates of the Detection Box: ({x1}, {y1}) -> ({x2}, {y2})\n")
            GLib.idle_add(stop_pipeline, user_data.pipeline, user_data.main_loop)
            return Gst.PadProbeReturn.DROP

    return Gst.PadProbeReturn.OK

# --- Utility: Stop Pipeline ---
def stop_pipeline(pipeline, main_loop):
    try:
        print("Stopping pipeline...")
        pipeline.set_state(Gst.State.NULL)
        Gst.deinit()
        print("Pipeline stopped.")
        if main_loop is not None:
            main_loop.quit()
        os._exit(0)
    except Exception as e:
        print(f"Failed to stop pipeline: {e}")
    return False

# --- Main Execution ---
if __name__ == "__main__":
    activate_hailo_env()
    Gst.init(None)
    main_loop = GLib.MainLoop()
    dummy_pipeline = Gst.Pipeline.new("dummy-pipeline")
    user_data = UserAppCallback(dummy_pipeline, main_loop)
    app = GStreamerDetectionApp(app_callback, user_data)
    user_data.pipeline = app.pipeline

    try:
        print("Running chip detection pipeline...")
        app.run()
        main_loop.run()
    except Exception as e:
        print(f"Application terminated: {e}")
    finally:
        stop_pipeline(user_data.pipeline, user_data.main_loop)