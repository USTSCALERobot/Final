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
    def __init__(self, root, ic_name, out_dir, num_images, deg):
        self.__root = root
        self.__root.title("Countdown + Counter")
        self.__root.bind("q", lambda event: self.close_app())

        self.__ic_name = ic_name
        self.__deg = deg  # NEW: degree from CLI

        # Countdown logic
        self.__default_delay = 1          # normal capture every 1 sec
        self.__interval_delay = 10        # every N images, wait 10 sec
        self.__images_interval = num_images
        self.__countdown_value = self.__default_delay

        self.__counter_value = 0
        self.__out_dir = out_dir
        self.__num_photos = 0

        # GUI labels
        self.__countdown_label = tk.Label(root, text=f"Countdown: {self.__countdown_value}", font=("Arial", 24))
        self.__countdown_label.pack(pady=10)

        self.__counter_label = tk.Label(root, text=f"Counter: {self.__counter_value}", font=("Arial", 24))
        self.__counter_label.pack(pady=10)

        self.__degree_label = tk.Label(root, text=f"Degree: {self.__deg}", font=("Arial", 24))
        self.__degree_label.pack(pady=10)

        self.update_countdown()

    def close_app(self):
        print(f"Took {self.__num_photos} photos.")
        self.__root.destroy()

    def update_countdown(self):
        self.__countdown_label.config(text=f"Countdown: {self.__countdown_value}")
        self.__countdown_value -= 1

        if self.__countdown_value < 0:
            self.capture_image()
            self.update_counter()

            # Reset countdown depending on interval
            if self.__counter_value % self.__images_interval == 0:
                self.__countdown_value = self.__interval_delay
            else:
                self.__countdown_value = self.__default_delay

        self.__root.after(1000, self.update_countdown)

    def update_counter(self):
        self.__counter_value += 1
        self.__counter_label.config(text=f"Counter: {self.__counter_value}")

    def capture_image(self):
        filename = self.generate_filename(self.__ic_name, self.__deg, self.__counter_value)
        script_dir = os.path.dirname(os.path.relpath(__file__))
        output_path = os.path.join(script_dir, self.__out_dir, filename)

        cap = cv2.VideoCapture(gstreamer_pipeline(), cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            print("Error: Unable to open camera")
            return

        time.sleep(0.5)
        ret, frame = cap.read()
        if ret and frame is not None:
            cv2.imwrite(output_path, frame)
            print(f"Saved: {output_path}")
        else:
            print("Error: Failed to capture image")

        cap.release()
        self.__num_photos += 1

    def generate_filename(self, ic_name, deg, counter):
        timestamp = time.strftime("%Y-%m-%d_%H.%M.%S")
        return f"{ic_name}_{deg}deg_#{counter:02d}_{timestamp}.jpg"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PCB IC dataset capture tool")
    parser.add_argument("--ic", required=True, help="Name of the IC being photographed")
    parser.add_argument("--deg", type=int, required=True, help="Angle of IC orientation")
    parser.add_argument("--out", type=str, default="pcb_ic_dataset", help="Output directory")
    parser.add_argument("--images", type=int, default=50,
                        help="Every N images, wait 10 seconds instead of 1")
    args = parser.parse_args()

    root = tk.Tk()
    app = _CounterApp(root, args.ic, args.out, args.images, args.deg)
    root.mainloop()
