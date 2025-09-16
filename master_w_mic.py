#!/usr/bin/env python3
import subprocess
import sys
import os
import time

# --- Configuration: Update these paths as needed ---
CHIP_VISION_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/chipvisionhandler2.py"
OCR_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/ocrhandler2.py"
ARM_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/phx_articulate2/Pick_coord_from_crop_txt2.py"
MOTOR2_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/Motor_Drive_After_OCR.py"
UI_HANDLER = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/UIChipRequest.py"

def run_ui_chip_request():
    #need to do a 'do while' or 'while' loop to wait for user to have entered/submitted chip request
    print("Asking user to enter specific chip")
    #run ui chip request code
    result = subprocess.run(["python3", UI_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ UI Chip Request Handler failed with return code {result.returncode}")
    print("✅ UI Chip Request Successful")

def run_chip_vision_handler():
    print(">>> Starting Chip Vision Handler...")
    # Run the chip vision handler script
    result = subprocess.run(["python3", CHIP_VISION_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ Chip Vision Handler failed with return code {result.returncode}")
    print("✅ Chip Vision Handler completed successfully.")

def run_ocr_handler2():
    print(">>> Starting OCR Handler...")
    # Run the OCR handler script
    result = subprocess.run(["python3", OCR_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ OCR Handler failed with return code {result.returncode}")
    print("✅ OCR Handler completed successfully.")

def run_arm_handler():
    print(">> Starting ARM Handler...")
    result = subprocess.run(["python3",ARM_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ ARM Handler failed with return code {result.returncode}")
    print("✅ ARM Handler completed successfully.")
def run_motor2_handler():
    print(">> Starting ARM Handler...")
    result = subprocess.run(["python3",MOTOR2_HANDLER])
    if result.returncode != 0:
        sys.exit(f"❌ MOTOR Handler failed with return code {result.returncode}")
    print("✅ ARM Handler completed successfully.")
def main():
    run_ui_chip_request()
    time.sleep(1)
    # Ensure that any required environment variables are set or activate environment here if needed.
    print(">>> Master: Running Chip Vision and OCR Handlers sequentially...")
    run_chip_vision_handler()
    # Optional: wait a moment to ensure resources are freed
    time.sleep(1)
    
    run_ocr_handler2()
    time.sleep(1)
    run_motor2_handler()
    time.sleep(1)
    run_arm_handler()
    print(">>> Master: All processes completed successfully.")

if __name__ == "__main__":
    main()