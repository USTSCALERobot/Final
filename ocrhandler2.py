#!/usr/bin/env python3
import os
import subprocess
import sys
import time

# --- Configuration ---
HAILO_ENV_SCRIPT = "/home/scalepi/hailo-rpi5-examples/setup_env.sh"
HAILO_VENV_PATH = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi5_examples/bin/activate"
OCR_SCRIPT = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/beltocr2.py"
SAVE_FOLDER = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE = os.path.join(SAVE_FOLDER, "latest_detection.txt")
OCR_SAVE_PATH = "/home/scalepi/Desktop/testOCR/rotationtest.png"

# --- Environment Activation ---
def activate_env():
    if os.getenv("HAILO_ENV_ACTIVATED") == "1":
        print("✅ Environment already activated.")
        return
    print("🔧 Activating environment...")
    cmd = (
        f"bash -c 'source {HAILO_ENV_SCRIPT} && "
        f"source {HAILO_VENV_PATH} && "
        f"export HAILO_ENV_ACTIVATED=1 && env'"
    )
    result = subprocess.run(cmd, shell=True, executable="/bin/bash",
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"❌ Error activating environment: {result.stderr}")
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        os.environ[key] = value
    print("✅ Environment activated successfully.")

# --- Read Detection File ---
def read_detection_file():
    if not os.path.exists(DETECTION_FILE):
        sys.exit("❌ Detection file not found. Ensure chip detection succeeded.")
    with open(DETECTION_FILE, "r") as f:
        lines = f.readlines()
    if len(lines) < 2:
        sys.exit("❌ Detection file format error. Expected at least two lines.")
    cropped_line = lines[0].strip()
    if not cropped_line.startswith("Cropped Photo Location:"):
        sys.exit("❌ Unexpected format in detection file.")
    parts = cropped_line.split(",", 1)
    if len(parts) < 2:
        sys.exit("❌ Couldn't parse cropped image path.")
    return parts[1].strip()

# --- Run OCR ---
def run_ocr():
    image_path = read_detection_file()
    print(f"Running OCR on image: {image_path}")
    cmd = ["python3", OCR_SCRIPT, "--image", image_path, "--save_path", OCR_SAVE_PATH]
    print("▶", " ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"❌ OCR processing failed ({result.returncode})")
    print("✅ OCR processing completed.")

# --- Cleanup Detection Header ---
def cleanup_detection_header():
    if not os.path.exists(DETECTION_FILE):
        return
    with open(DETECTION_FILE, "r") as f:
        lines = f.readlines()
    filtered = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line.startswith("Cropped Photo Location:"):
            skip_next = True
            continue
        filtered.append(line)
    with open(DETECTION_FILE, "w") as f:
        f.writelines(filtered)
    print("✅ Removed detection header from text file.")

# --- Delete Cropped Images ---
def delete_cropped_images():
    for fname in os.listdir(SAVE_FOLDER):
        if fname.startswith("chip_cropped_") and fname.endswith(".png"):
            path = os.path.join(SAVE_FOLDER, fname)
            try:
                os.remove(path)
                print(f"🗑️ Deleted {path}")
            except Exception as e:
                print(f"⚠️ Could not delete {path}: {e}")

# --- Main Workflow ---
def main():
    activate_env()
    time.sleep(1)
    run_ocr()
    cleanup_detection_header()
    delete_cropped_images()

if __name__ == "__main__":
    main()
