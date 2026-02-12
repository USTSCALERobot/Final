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

class _CounterApp:
    def __init__(self, root, ic_name, delay, out_dir, num_images):
        self.__root = root
        self.__root.title("Countdown + Counter")
        self.__root.bind("q", lambda event: self.close_app()) # Quit on 'q'

        self.__ic_name = ic_name
        self.__countdown_value = delay
        self.__countdown_start = delay
        self.__counter_value = 0
        self.__counter_max = num_images
        self.__out_dir = out_dir
        self.__num_photos = 0;
        self.__num_positions = 1; # 1 is a stop gap solution for when user only goes through 1 counter run

        self.__countdown_label = tk.Label(root, text=f"Countdown: {self.__countdown_value}", font=("Arial", 24))
        self.__countdown_label.pack(pady=10)

        self.__counter_label = tk.Label(root, text=f"Counter: {self.__counter_value}", font=("Arial", 24))
        self.__counter_label.pack(pady=10)

        self.update_countdown() # every measurement depends on successful countdowns

    def close_app(self):
        print(f"Took {self.__num_photos} photos across {self.__num_positions} different IC positions.")
        self.__root.destroy()

    def update_countdown(self):
        self.__countdown_label.config(text=f"Countdown: {self.__countdown_value}")
        self.__countdown_value -= 1

        if self.__countdown_value < 0:
            self.__countdown_value = self.__countdown_start  # restart countdown
            self.capture_image()
            self.update_counter()

        self.__root.after(1000, self.update_countdown)  # run again in 1 second

    def update_counter(self):
        self.__counter_value += 1
        self.__counter_label.config(text=f"Counter: {self.__counter_value}")

        if self.__counter_value == self.__counter_max:
            self.__counter_value = 0  # restart counter
            self.__num_positions += 1
    
    def gstreamer_pipeline(
        self,
        sensor_id=0,
        capture_width=1920,
        capture_height=1080,
        framerate=60,
        flip_method=0,
    ):
        return (
        "nvarguscamerasrc sensor-id=%d ! "
        "video/x-raw(memory:NVMM), width=(int)%d, height=(int)%d, "
        "framerate=(fraction)%d/1, format=NV12 ! "
        "nvvidconv flip-method=%d ! "
        "video/x-raw, format=(string)BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=(string)BGR ! appsink"
        % (
            sensor_id,
            capture_width,
            capture_height,
            framerate,
            flip_method,
        )
    )

    def capture_image(self):
        filename = self.generate_filename(self.__ic_name, self.__num_positions, self.__counter_value)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, self.__out_dir, filename)
        cap = cv2.VideoCapture(self.gstreamer_pipeline(), cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            print("Error: Unable to open camera")
            return
        time.sleep(0.5) # Allow camera auto‑exposure to settle
        ret, frame = cap.read()
        if ret and frame is not None:
            cv2.imwrite(output_path, frame)
            print(f"Success: Saved image to {output_path}")
        else:
            print("Error: Failed to capture image")
        cap.release()
        self.__num_photos += 1

    def generate_filename(self, ic_name, position, counter):
        timestamp = time.strftime("%Y-%m-%d_%H:%M.%S")
        return f"{ic_name}_{position:02d}_{counter+1:02d}_{timestamp}.jpg"

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