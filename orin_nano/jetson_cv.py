# Code based on simple_camera.py from JetsonHacks repo: https://github.com/JetsonHacksNano/CSI-Camera.git

# Main idea here is that camera capture feed is provided using Argus API in the terminal:
# https://docs.nvidia.com/jetson/archives/r35.6.1/DeveloperGuide/SD/Multimedia/GstreamerBasedCameraCapture.html
# Sample terminal command (will open a window): gst-launch-1.0 nvarguscamerasrc sensor-id=0 ! nvvidconv ! xvimagesink

import cv2

""" 
gstreamer_pipeline returns a GStreamer pipeline for capturing from the CSI camera
Flip the image by setting the flip_method (most common values: 0 and 2)
display_width and display_height determine the size of each camera pane in the window on the screen
Default 1920x1080 displayd in a 1/4 size window
"""
def gstreamer_pipeline(
    sensor_id=0,
    capture_width=1920,
    capture_height=1080,
    display_width=1280,
    display_height=720,
    framerate=60,
    flip_method=0,
):
    return (
        "nvarguscamerasrc sensor-id=%d ! "
        "queue !" # Included queues between arguments to improve feed performance
        "video/x-raw(memory:NVMM), width=(int)%d, height=(int)%d, framerate=(fraction)%d/1, format=NV12 ! "
        "queue !"
        "nvvidconv flip-method=%d ! "
        "queue !"
        "video/x-raw, width=(int)%d, height=(int)%d, format=(string)BGRx ! "
        "queue !"
        "videoconvert ! "
        "queue !"
        "video/x-raw, format=(string)BGR ! appsink sync=0"
        % (
            sensor_id,
            capture_width,
            capture_height,
            framerate,
            flip_method,
            display_width,
            display_height,
        )
    )


def show_camera():
    window_title = "PCB Placement Verifier"
    print(gstreamer_pipeline()) # To flip the image, modify the flip_method parameter (0 and 2 are the most common)
    video_capture = cv2.VideoCapture(gstreamer_pipeline(), cv2.CAP_GSTREAMER)
    if video_capture.isOpened():
        try:
            window_handle = cv2.namedWindow(window_title, cv2.WINDOW_AUTOSIZE)
            while True:
                ret_val, frame = video_capture.read()
                height, width, _ = frame.shape
                cropped = frame[height//2 : height, 240 : 720] # Keep non-corrupted portion of camera feed
                # Check to see if the user closed the window
                # Under GTK+ (Jetson Default), WND_PROP_VISIBLE does not work correctly. Under Qt it does
                # GTK - Substitute WND_PROP_AUTOSIZE to detect if window has been closed by user
                if cv2.getWindowProperty(window_title, cv2.WND_PROP_AUTOSIZE) >= 0:
                    cv2.imshow(window_title, cropped) # Centering requires 30 degrees offset right relative to camera
                else:
                    break 
                keyCode = cv2.waitKey(10) & 0xFF
                # Stop the program on the ESC key or 'q'
                if keyCode == 27 or keyCode == ord('q'):
                    break
        finally:
            video_capture.release()
            cv2.destroyAllWindows()
    else:
        print("Error: Unable to open camera")

if __name__ == "__main__":
    show_camera()
