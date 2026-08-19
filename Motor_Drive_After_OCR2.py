########################################################################
# Document: Motor_Drive_After_OCR2.py
# Project: SCALE Automated Vision System
# Institution: University of St. Thomas
# Contributors: Dan Walczak, Bennett Nelson, Erik Perez, 
#               Louis Stevenson, Ryan Bercich, Theodore Thorpe
# Description: 
#   TODO: add description...
########################################################################

import gpiod
import time
import os
import re
import math
LED_PIN = 24
SAVE_FOLDER = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE = os.path.join(SAVE_FOLDER, "latest_detection.txt")

chip = gpiod.Chip('/dev/gpiochip0')
request = chip.request_lines(
    config={LED_PIN: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)},
    consumer="motor_after_ocr"
)

def get_required_run_time():
    required_time = 9.25 # default fallback
    if os.path.exists(DETECTION_FILE):
        with open(DETECTION_FILE, 'r') as f:
            for line in f:
                m = re.match(r'^\s*Required_Belt_Run_Time:\s*([0-9.]+)', line)
                if m:
                    required_time = float(m.group(1))
                    break
    return required_time

def main():
    run_time = get_required_run_time()
    
    
    request.set_value(LED_PIN, gpiod.line.Value.ACTIVE)
    print("ON")
    print(f"Running motor for {run_time:.2f}s based on OCR calculations)")
    time.sleep(run_time)  # new time differential for multiple chips 
    request.set_value(LED_PIN, gpiod.line.Value.INACTIVE)
    print("OFF")
    time.sleep(1)  # Sleep for one second
    request.release()
    chip.close()
if __name__ == "__main__":
    main()
