#!/usr/bin/env python3
import subprocess
import sys
import os
import time
from pathlib import Path

# --- Configuration: Update these paths as needed ---
CHIP_VISION_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/chipvision3.py"
OCR_HANDLER         = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/ocrhandler2.py"
ARM_HANDLER         = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/phx_articulate2/Pick_coord_from_crop_txt3.py"
MOTOR2_HANDLER      = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/Motor_Drive_After_OCR2.py"
UI_HANDLER          = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/UIChipRequest2.py"

SAVE_FOLDER    = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE = os.path.join(SAVE_FOLDER, "latest_detection.txt")
FLAG_FILE      = os.path.join(SAVE_FOLDER, "multi_capture.flag")

# Optional: tune between-frames nudge in one place (both CV + Arm respect this via env)
EXTRA_RUN_SEC = os.environ.get("EXTRA_RUN_SEC", "1.0")  # default 1.0 s

# Hailo venv python (used for chipvision3 which needs hailo/gstreamer)
# HAILO_PYTHON = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi_examples/bin/python3"
# Attempt to change python to 3.13.5 aka current python in venv, but fallback to "python3" if that path doesn't exist (e.g., if venv was recreated and python version changed)
HAILO_PYTHON = "/usr/bin/python3"

def run_ui_chip_request():
    print("\n=== UI: request input (part/circuit, large-part toggle) ===")
    result = subprocess.run(["python3", UI_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ UI Chip Request failed with return code {result.returncode}")
    print("✅ UI complete.")

def run_chip_vision_handler():
    print("\n=== Vision: detection + crops (Frame 1, optional Frame 2) ===")
    env = os.environ.copy()
    env["EXTRA_RUN_SEC"] = EXTRA_RUN_SEC

    # changed from chat suggestion
    env["TAPPAS_POST_PROC_DIR"] = "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes"
    env["LD_LIBRARY_PATH"] = "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes:" + env.get("LD_LIBRARY_PATH", "")

    try:
        result = subprocess.run(
            [HAILO_PYTHON, CHIP_VISION_HANDLER],
            env=env,
            timeout=300  # 5-minute hard ceiling; adjust if your belt run is longer
        )
    except subprocess.TimeoutExpired:
        print("⏱️ Vision stage timed out after 5 minutes — killing subprocess.")
        return  # let the detection-file check below handle the failure gracefully
    except KeyboardInterrupt:
        print("🛑 Vision stage interrupted by user.")
        raise  # re-raise so main() can exit cleanly

    if result.returncode not in (0, -2, -15):
        # -2 = SIGINT, -15 = SIGTERM — both are acceptable interrupt exits
        print(f"⚠️ Chip Vision Handler exited with code {result.returncode} (continuing)")

    print("✅ Vision completed.")

def run_ocr_handler():
    print("\n=== OCR: parse frames, OCR crops, append results ===")
    result = subprocess.run([HAILO_PYTHON, OCR_HANDLER])
    # result = subprocess.run(["python3", OCR_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ OCR Handler failed with return code {result.returncode}")
    print("✅ OCR completed.")

def run_motor2_handler(seconds=None):
    print("\n=== Belt: move parts to arm station ===")
    cmd = ["python3", MOTOR2_HANDLER]
    if seconds is not None:
        cmd += ["--seconds", str(seconds)]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"❌ Motor-to-Arm failed with return code {result.returncode}")
    print("✅ Belt run completed.")

def run_arm_handler():
    print("\n=== ARM: pick frame 1 → 1s belt nudge → pick frame 2; drop-offs via Circuits.txt ===")
    env = os.environ.copy()
    env["EXTRA_RUN_SEC"] = EXTRA_RUN_SEC
    result = subprocess.run(["python3", ARM_HANDLER], env=env)
    if result.returncode != 0:
        sys.exit(f"❌ ARM Handler failed with return code {result.returncode}")
    print("✅ ARM sequence completed.")

def _file_has_frames(path):
    try:
        txt = Path(path).read_text()
    except FileNotFoundError:
        return False, "detection file missing"
    f1 = "FRAME=1" in txt or "Frame: 1" in txt
    f2 = "FRAME=2" in txt or "Frame: 2" in txt
    return True, ("Frame1+2" if (f1 and f2) else ("Frame1 only" if f1 else "no Frame markers"))

def main():
    # 1) UI request (sets chip_request_input.txt and possibly multi_capture.flag)
    run_ui_chip_request()
    time.sleep(0.5)

    # 2) Vision (creates latest_detection.txt with FRAME sections + chip.png/chip2.png)
    run_chip_vision_handler()
    time.sleep(0.5)

    ok, status = _file_has_frames(DETECTION_FILE)
    if not ok:
        sys.exit("❌ latest_detection.txt not found after vision stage.")
    print(f"ℹ️ Detection file status: {status}")
    print("Starting OCR")

    # 3) OCR (reads FRAME sections, appends OCR blocks that include 'Frame: N')
    run_ocr_handler()
    time.sleep(0.5)

    # 4) Move belt to arm (long run). Tune seconds or leave None for motor script default.
    run_motor2_handler(seconds=None)  # e.g., None to use 9.25s default inside the motor script
    time.sleep(0.5)

    # 5) ARM picks: does Frame 1 → 1s nudge → Frame 2 (internally), then drop-offs
    run_arm_handler()

    print("\n>>> Master: All processes completed successfully.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Master process interrupted by user. Exiting.")
        sys.exit(0)