import sys
import os
import subprocess

HAILO_ENV_SCRIPT = "/home/scalepi/hailo-rpi5-examples/setup_env.sh"
HAILO_VENV_PATH = "/home/scalepi/hailo-rpi5-examples/venv_hailo_rpi_examples/bin/activate"

def auto_activate_venv():
    if os.getenv("HAILO_ENV_ACTIVATED") == "1":
        return

    print("Activating Hailo environment...")
    cmd = (
        f"bash -c 'source {HAILO_ENV_SCRIPT} && "
        f"source {HAILO_VENV_PATH} && "
        f"export HAILO_ENV_ACTIVATED=1 && env'"
    )
    r = subprocess.run(cmd, shell=True, executable="/bin/bash",
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("Warning: Could not activate Hailo environment.")
        return

    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        if k:
            os.environ[k] = v
    os.environ.setdefault("TAPPAS_POST_PROC_DIR",
        "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes")

    venv_python = os.path.join(os.path.dirname(HAILO_VENV_PATH), "python3")
    if os.path.exists(venv_python):
        # Re-execute using the venv's python
        os.execve(venv_python, [venv_python] + sys.argv, os.environ)

# MUST run this before we try to import cv2
auto_activate_venv()

import cv2

# Add parent directory to path so we can import beltocr2
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import beltocr2

def test_contour_center():
    print("=== Vision Accuracy Test ===")
    
    # We will use the save folder configured in beltocr2
    save_folder = beltocr2.SAVE_FOLDER
    
    # Parse the detection file to get a real image and its actual coordinates
    frames = beltocr2.parse_detection_frames(beltocr2.DETECTION_FILE)
    if not frames:
        print(f"No detections found in {beltocr2.DETECTION_FILE}.")
        print("Please run the main vision pipeline once first.")
        return

    # Grab the first crop from the first frame
    first_frame = sorted(frames.keys())[0]
    first_crop = frames[first_frame][0]
    
    # Unpack the real data
    full_path, test_image, (x1, y1, x2, y2) = first_crop
    
    if not os.path.exists(test_image):
        print(f"Test image not found at {test_image}")
        return

    print(f"Testing vision accuracy on real image: {test_image}")
    print(f"Real AI Bounding Box from file: X({x1} -> {x2}), Y({y1} -> {y2})")
    
    try:
        
        print("\n--- Running mask_and_rotate ---")
        # Run the updated function
        (cx, cy), (wb, hb), angle, crop_w, crop_h = beltocr2.mask_and_rotate(test_image, idx="TEST")
        
        print(f"Crop Image Size: {crop_w} x {crop_h} pixels")
        print(f"Local Contour Center (pixels): cx={cx:.2f}, cy={cy:.2f}")
        print(f"Chip Dimensions (pixels): width={wb:.2f}, height={hb:.2f}")
        print(f"Calculated Angle: {angle:.2f}°")
        
        # Translate to global
        ncx = cx / crop_w
        ncy = cy / crop_h
        
        print(f"Normalized Local Center: ncx={ncx:.4f}, ncy={ncy:.4f}")
        
        # Compare against the old AI center logic
        ai_center_x = (x1 + x2) / 2
        ai_center_y = (y1 + y2) / 2
        
        true_global_x = x1 + ncx * (x2 - x1)
        true_global_y = y1 + ncy * (y2 - y1)
        
        print("\n--- Global Coordinate Results ---")
        print(f"Old AI Bounding Box Center:  ({ai_center_x:.6f}, {ai_center_y:.6f})")
        print(f"New True Contour Center:     ({true_global_x:.6f}, {true_global_y:.6f})")
        
        diff_x = abs(true_global_x - ai_center_x)
        diff_y = abs(true_global_y - ai_center_y)
        print(f"Absolute Correction Shift:   dX={diff_x:.6f}, dY={diff_y:.6f}")
        
        debug_output = os.path.join(save_folder, "chip_center_debug_TEST.png")
        print(f"\nSuccess! A debug image with a red dot showing the exact calculated center has been saved to:")
        print(f"   -> {debug_output}")
        
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    test_contour_center()
