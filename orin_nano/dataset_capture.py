# Description:
# Streamline image collection for the PCB camera's IC dataset.
# Approach:
# 1. Run the script in CLI to pass arguments.
# 2. Start up image capture GUI using CLI arguments.
# 3. GUI shows number of seconds until next pic taken and a counter at a specific count.
# 4. Pictures taken will be stored under specified subdirectory under dynamically generated file names.
# 5. Steps 2 and 3 repeat indefinitely until 'q' is pressed to close program.
# Notes: 
# - Program will automatically take pictures upon successful countdowns
# - Counter indicates when to reposition IC for robust data collection
# - ALWAYS exit app using 'q' for metrics
# - IC name is the only required argument; the rest are optional and have default values

import cv2
import time
import os
import argparse
import tkinter as tk
from jetson_cv import gstreamer_pipeline

class _CounterApp:
    def __init__(self, root, ic_name, delay, out_dir, num_images):
        self.__root = root
        self.__root.title("Countdown + Counter")
        self.__root.bind("q", lambda event: self.close_app()) # * Quit on 'q'

        self.__ic_name = ic_name
        self.__countdown_value = delay
        self.__countdown_start = delay
        self.__counter_value = 0
        self.__counter_max = num_images
        self.__out_dir = out_dir
        self.__num_photos = 0
        self.__angles = [0, 45, 60, 90]
        self.__curr_angle = 0
        self.__capture_complete = False

        self.__countdown_label = tk.Label(root, text=f"Countdown: {self.__countdown_value}", font=("Arial", 24))
        self.__countdown_label.pack(pady=10)

        self.__counter_label = tk.Label(root, text=f"Counter: {self.__counter_value}", font=("Arial", 24))
        self.__counter_label.pack(pady=10)

        self.__degree_label = tk.Label(root, text=f"Degree: {self.__angles[self.__curr_angle]}", font=("Arial", 24))
        self.__degree_label.pack(pady=10)

        self.update_countdown() # * every measurement depends on successful countdowns

    def close_app(self):
        if self.__curr_angle == len(self.__angles) - 1:
            print(f"Took {self.__num_photos} photos across {len(self.__angles)} different IC angle orientation(s).")
        else:
            print(f"Took {self.__num_photos} photos across {self.__curr_angle + 1} different IC angle orientation(s).")
        self.__root.destroy()

    def update_countdown(self):
        if self.__capture_complete:
            return

        self.__countdown_label.config(text=f"Countdown: {self.__countdown_value}")
        self.__countdown_value -= 1

        if self.__countdown_value < 0:
            self.__countdown_value = self.__countdown_start  # * restart countdown
            self.capture_image()
            self.update_counter()

        self.__root.after(1000, self.update_countdown)  # * run again in 1 second

    def update_counter(self):
        if self.__capture_complete:
            return

        if self.__counter_value == self.__counter_max and self.__curr_angle != len(self.__angles) - 1:
            self.__counter_value = 0  # restart counter
            self.__curr_angle += 1
            self.__degree_label.config(text=f"Degree: {self.__angles[self.__curr_angle]}")
        elif self.__counter_value == self.__counter_max and self.__curr_angle == len(self.__angles) - 1:
            self.__capture_complete = True;
            print("Capture complete for all angles.")
            self.__countdown_label.config(text="Capture complete. Press 'q' to exit.")
            return
        self.__counter_value += 1 # * Keeps counter and degree fields in sync when placed down here
        self.__counter_label.config(text=f"Counter: {self.__counter_value}")

    def capture_image(self):
        filename = self.generate_filename(self.__ic_name, self.__angles[self.__curr_angle], self.__counter_value)
        script_dir = os.path.dirname(os.path.relpath(__file__))
        output_path = os.path.join(script_dir, self.__out_dir, filename)
        cap = cv2.VideoCapture(gstreamer_pipeline(), cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            print("Error: Unable to open camera")
            return
        time.sleep(0.5) # * Allow camera auto‑exposure to settle
        ret, frame = cap.read()
        if ret and frame is not None:
            cv2.imwrite(output_path, frame)
            print(f"Success: Saved image to {output_path}")
        else:
            print("Error: Failed to capture image")
        cap.release()
        self.__num_photos += 1

    def generate_filename(self, ic_name, angle, counter):
        timestamp = time.strftime("%Y-%m-%d_%H:%M.%S")
        return f"{ic_name}_{angle}deg_#{counter+1:02d}_{timestamp}.jpg"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--ic", required=True, help="Name of the IC being photographed")
    parser.add_argument("--delay", type=int, default=5, help="Seconds between image captures")
    parser.add_argument("--out", type=str, default="pcb_ic_dataset", help="Image output subdirectory")
    parser.add_argument("--images", type=int, default=50, help="Number of photos to take between repositions")
    args = parser.parse_args()
    root = tk.Tk()
    app = _CounterApp(root, args.ic, args.delay, args.out, args.images)
    root.mainloop()