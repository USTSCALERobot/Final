# Capture photos instead of live camera feed to collect images for the project's dataset

import cv2
import time
import os

def gstreamer_pipeline(
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

def capture_image():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, "pcb_ic_dataset", "dummy_image.jpg")
    cap = cv2.VideoCapture(gstreamer_pipeline(), cv2.CAP_GSTREAMER)
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

if __name__ == "__main__":
    capture_image()
