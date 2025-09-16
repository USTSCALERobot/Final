#!/usr/bin/env python3
import subprocess
import sys
import os
import time
from pathlib import Path  # ✅ minimal fix: used by _file_has_frames

# --- Configuration: Update these paths as needed ---
CHIP_VISION_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/chipvisionhandler3.py"
OCR_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/ocrhandler2.py"
ARM_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/phx_articulate2/Pick_coord_from_crop_txt3.py"
MOTOR2_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/Motor_Drive_After_OCR2.py"
UI_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/UIChipRequest2.py"

SAVE_FOLDER         = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE      = os.path.join(SAVE_FOLDER, "latest_detection.txt")
FLAG_FILE           = os.path.join(SAVE_FOLDER, "multi_capture.flag")

# Optional: tune between-frames nudge in one place (both CV + Arm respect this via env)
EXTRA_RUN_SEC = os.environ.get("EXTRA_RUN_SEC", "1.0")  # default 1.0 s

def run_ui_chip_request():
    print("\n=== UI: request input (part/circuit, large-part toggle) ===")
    result = subprocess.run(["python3", UI_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ UI Chip Request failed with return code {result.returncode}")
    print("✅ UI complete.")

def run_chip_vision_handler():
    print("\n=== Vision: detection + crops (Frame 1, optional Frame 2) ===")
    # Propagate EXTRA_RUN_SEC so the CV script can honor your belt nudge timing
    env = os.environ.copy()
    env["EXTRA_RUN_SEC"] = EXTRA_RUN_SEC
    result = subprocess.run(["python3", CHIP_VISION_HANDLER], env=env)
    if result.returncode != 0:
        sys.exit(f"❌ Chip Vision Handler failed with return code {result.returncode}")
    print("✅ Vision completed.")

def run_ocr_handler():
    print("\n=== OCR: parse frames, OCR crops, append results ===")
    result = subprocess.run(["python3", OCR_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ OCR Handler failed with return code {result.returncode}")
    print("✅ OCR completed.")

def run_motor2_handler(seconds=None):
    # This is the long run to bring the chips to the arm station
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
    env["EXTRA_RUN_SEC"] = EXTRA_RUN_SEC  # robot-pick script uses this for the 1s between frames
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

    # 4) Move belt to arm (long run). You can tune this seconds value or leave None to use motor script default
    run_motor2_handler(seconds=None)  # e.g., None to use 9.25s default inside the motor script
    time.sleep(0.5)

    # 5) ARM picks: does Frame 1 → 1s nudge → Frame 2 (internally), then drop-offs
    run_arm_handler()

    print("\n>>> Master: All processes completed successfully.")

if __name__ == "__main__":
    main()
