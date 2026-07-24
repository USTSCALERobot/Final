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
    base_time = 10.48
    
    # Base distance we want the belt to travel (calculated from base_time = 10.48s)
    # Using linear model for base distance since 10.48s > 2.61s:
    # Distance = 2.2163 * 10.48 + 0.0909 = 23.3177 cm
    base_distance = 23.3177
    
    # Distance traveled at the end of the acceleration phase (t=2.61s)
    dist_at_2_61 = 0.0274 * (2.61**2) + 2.0731 * 2.61 + 0.2780 # ~5.8754 cm
    
    # Calculate how far the belt has ALREADY traveled during the OCR phase (max_offset)
    if max_offset <= 0:
        distance_already_traveled = 0.0
    elif max_offset <= 2.61:
        # Quadratic model (acceleration phase)
        distance_already_traveled = 0.0274 * (max_offset**2) + 2.0731 * max_offset + 0.2780
    else:
        # Acceleration phase + steady-state linear phase
        distance_already_traveled = dist_at_2_61 + 2.2163 * (max_offset - 2.61)
        
    # Calculate the remaining distance the belt needs to travel
    remaining_distance = max(0.0, base_distance - distance_already_traveled)
    
    # Calculate how much TIME it takes to travel that remaining distance
    if remaining_distance <= 0:
        run_time = 0.0
    elif remaining_distance <= dist_at_2_61:
        # Reverse Quadratic: 0.0274*t^2 + 2.0731*t + (0.2780 - remaining_distance) = 0
        import math
        a = 0.0274
        b = 2.0731
        c = 0.2780 - remaining_distance
        
        # Protect against imaginary values and negative time
        discriminant = b**2 - 4*a*c
        if discriminant < 0:
            run_time = 0.0
        else:
            t = (-b + math.sqrt(discriminant)) / (2*a)
            run_time = max(0.0, t)
    else:
        # Time for acceleration phase (2.61s) + time for remaining distance at steady velocity
        run_time = 2.61 + (remaining_distance - dist_at_2_61) / 2.2163
    
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
