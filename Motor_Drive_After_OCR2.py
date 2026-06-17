import gpiod
import time
import os
import re

LED_PIN = 24
SAVE_FOLDER = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE = os.path.join(SAVE_FOLDER, "latest_detection.txt")

chip = gpiod.Chip('/dev/gpiochip0')
request = chip.request_lines(
    config={LED_PIN: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)},
    consumer="motor_after_ocr"
)

def get_max_time_offset():
    max_offset = 0.0
    if os.path.exists(DETECTION_FILE):
        with open(DETECTION_FILE, 'r') as f:
            for line in f:
                m = re.match(r'^\s*(?:Global_Max_)?Time_Offset:\s*([0-9.]+)', line)
                if m:
                    offset = float(m.group(1))
                    if offset > max_offset:
                        max_offset = offset
    return max_offset

def main():
    max_offset = get_max_time_offset()
    # Increased from 8.25 to 12.71 to run the belt an additional ~4.46 seconds, 
    # moving the chips ~10cm further down the belt to clear the camera mount.
    base_time = 12.5
    run_time = max(0.0, base_time - max_offset)
    
    #while(1):
    request.set_value(LED_PIN, gpiod.line.Value.ACTIVE)
    print("ON")
    print(f"Running motor for {run_time:.2f}s (Base: {base_time}s - Max Offset: {max_offset:.2f}s)")
    time.sleep(run_time)  # new time differential for multiple chips 
    request.set_value(LED_PIN, gpiod.line.Value.INACTIVE)
    print("OFF")
    time.sleep(1)  # Sleep for one second
    request.release()
    chip.close()
if __name__ == "__main__":
    main()
