import argparse
import socket
import struct
import cv2
import numpy as np
import sys
import os
import sys
import shlex
import time
from pathlib import Path

# --- Auto-Activate Hailo Environment ---
if os.environ.get("HAILO_ENV_ACTIVATED") != "1":
    print("Auto-activating Hailo environment...")
    script_path = os.path.abspath(__file__)
    args_str = " ".join(shlex.quote(arg) for arg in sys.argv[1:])
    
    bash_cmd = (
        f"cd /home/scalepi/hailo-apps && "
        f"source setup_env.sh && "
        f"cd - > /dev/null && "
        f"export HAILO_ENV_ACTIVATED=1 && "
        f"exec python {script_path} {args_str}"
    )
    os.execlp("bash", "bash", "-c", bash_cmd)
# ---------------------------------------

from ultralytics import YOLO
from collections import defaultdict

# Add phx_articulate2 to path so we can import kinematics and phx
phx_dir = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/phx_articulate2"
if phx_dir not in sys.path:
   sys.path.append(phx_dir)
import kinematics as kin
import phx

ROOT = Path(__file__).resolve().parent

def find_weights(explicit_weights: str | None = None) -> Path:
    if explicit_weights:
        return Path(explicit_weights).expanduser().resolve()

    candidates = [
        ROOT / "best_hailo_model",
        ROOT / "best_hailo_model" / "best.hef",
        ROOT / "weights" / "best.pt",
        ROOT / "best.pt",
        ROOT.parent / "runs" / "esp_live" / "weights" / "best.pt",
        ROOT.parent / "runs" / "esp_live" / "weights" / "last.pt",
    ]
    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Could not find a model weights file. Put best.hef in best_hailo_model/ or pass --weights."
    )

def recv_all(sock, size):
  data = b""
  while len(data)<size:
    packet = sock.recv(size-len(data))
    if not packet:
      return None
    data += packet
  return data

def go_to_pos(pickup_pos, theta0_4):
    try:
        joint_angles = kin.ik3(pickup_pos)
        theta4 = kin.calculate_theta_4(joint_angles, theta0_4)
        phx.set_wrist(theta4)
        phx.set_wse(joint_angles)
        phx.wait_for_completion()
    except ValueError as e:
        print(f"Error: Unable to reach position {pickup_pos}.")
        print(f"Details: {e}")
        return False
    return True

def set_gripper_rotation(ang_deg):
   difference = ang_deg - 180
   scaled_angle = 180 + (difference * 1.2)
   motor_position = (scaled_angle / 180) * 512
   phx.set_gripper(round(motor_position))

def main():
    parser = argparse.ArgumentParser(
        description="Receive JPEG frames over TCP from ESP32 and run YOLO inference"
    )
    parser.add_argument("--weights", default=None, help="Path to YOLO weights file")
    parser.add_argument("--host", default="10.42.0.1", help="Host address to bind on the Pi")
    parser.add_argument("--port", type=int, default=5000, help="TCP port")
    parser.add_argument("--imgsz", type=int, default=640, help="Input image size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--device", default="cpu", help="Inference device, e.g. cpu")
    args = parser.parse_args()

    # Create folders for saving images
    os.makedirs("good", exist_ok=True)
    os.makedirs("bad", exist_ok=True)
    good_count = 0
    bad_count = 0

    # Initialize arm
    print("Initializing robot arm...")
    phx.turn_on()
    current_pos = [18.5, 0.0, 23.0]
    current_theta = -90.0
    current_gripper_angle = 180.0
    print(f"Moving to starting position: {current_pos} with angle {current_gripper_angle}")
    go_to_pos(current_pos, current_theta)
    set_gripper_rotation(current_gripper_angle)

    # Load YOLO model
    weights_path = find_weights(args.weights)
    print(f"Loading model: {weights_path}")
    model = YOLO(str(weights_path))

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(1)
    server.settimeout(1.0) # Allow accept() to timeout so we can catch Ctrl+C

    print(f"Listening on {args.host}:{args.port}. Press Ctrl+C or 'q' in the video window to exit.")

    midpoints_x = defaultdict(list)

    try:
      while True:
        try:
          conn, addr = server.accept()
        except socket.timeout:
          continue # Timeout reached, loop back to check for KeyboardInterrupt
          
        print("Connected:", addr)

        while True:
          #read image length
          header = recv_all(conn,4)
          if not header:
            print("Connection closed by ESP32")
            break
          size = struct.unpack("!I", header)[0]
          
          #read JPEG
          jpeg = recv_all(conn,size)
          if not jpeg:
            print("Connection closed by ESP32 during frame")
            break
          img_array = np.frombuffer(jpeg, dtype=np.uint8)
          frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
          flipped = cv2.rotate(frame, cv2.ROTATE_180)
          
          if flipped is not None:
            # Run YOLO inference
            results = model(flipped, imgsz=args.imgsz, conf=args.conf, stream=False, device=args.device)
            
            # We use labels=False so we can draw our own custom labels, and set line_width for the box thickness
            annotated = results[0].plot(labels=False, line_width=2)
            
            # Extract OBB bounding boxes
            if hasattr(results[0], 'obb') and results[0].obb is not None:
                obb = results[0].obb
                if len(obb) > 0:
                    xywhr = obb.xywhr.cpu().numpy() # (N, 5) array: cx, cy, w, h, r
                    cls = obb.cls.cpu().numpy()
                    conf = obb.conf.cpu().numpy()
                    corners = obb.xyxyxyxy.cpu().numpy() # (N, 4, 2) array of corner points
                    
                    for box, k, c, corner in zip(xywhr, cls, conf, corners):
                        cx, cy, w, h, r = box
                        label = model.names[int(k)]
                        midpoints_x[label].append(cx)
                        
                        # Convert rotation from radians to degrees
                        r_deg = np.degrees(r)
                        
                        # Create custom label lines (removed class name)
                        lines = [
                            f"Conf: {c:.2f}",
                            f"Mid: ({cx:.1f}, {cy:.1f})",
                            f"Rot: {r_deg:.1f}deg"
                        ]
                        
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = 0.35
                        thickness = 1
                        line_spacing = 4
                        
                        # Calculate dimensions
                        text_sizes = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in lines]
                        max_w = max([size[0] for size in text_sizes])
                        total_h = sum([size[1] + line_spacing for size in text_sizes])
                        
                        # Find top right corner of OBB
                        top_right_x = int(np.max(corner[:, 0]))
                        top_right_y = int(np.min(corner[:, 1]))
                        
                        # 10px buffer from top right
                        start_x = top_right_x + 10
                        start_y = top_right_y
                        
                        # Draw background
                        cv2.rectangle(annotated, 
                                      (start_x, start_y), 
                                      (start_x + max_w + 10, start_y + total_h + 5), 
                                      (0, 0, 0), -1)
                        
                        # Draw lines
                        current_y = start_y + text_sizes[0][1] + 2
                        for i, line in enumerate(lines):
                            cv2.putText(annotated, line, (start_x + 5, current_y), font, font_scale, (255, 255, 255), thickness)
                            current_y += text_sizes[i][1] + line_spacing
            else:
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    xyxy = boxes.xyxy.cpu().numpy()
                    cls = boxes.cls.cpu().numpy()
                    conf = boxes.conf.cpu().numpy()
                    for box, k, c in zip(xyxy, cls, conf):
                        x1, y1, x2, y2 = box
                        label = model.names[int(k)]
                        mid_x = (x1 + x2) / 2
                        midpoints_x[label].append(mid_x)
                        
                        lines = [
                            f"Conf: {c:.2f}",
                            f"Mid: ({mid_x:.1f}, {(y1+y2)/2:.1f})"
                        ]
                        
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = 0.35
                        thickness = 1
                        line_spacing = 4
                        
                        text_sizes = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in lines]
                        max_w = max([size[0] for size in text_sizes])
                        total_h = sum([size[1] + line_spacing for size in text_sizes])
                        
                        top_right_x = int(x2)
                        top_right_y = int(y1)
                        
                        start_x = top_right_x + 10
                        start_y = top_right_y
                        
                        cv2.rectangle(annotated, 
                                      (start_x, start_y), 
                                      (start_x + max_w + 10, start_y + total_h + 5), 
                                      (0, 0, 0), -1)
                        
                        current_y = start_y + text_sizes[0][1] + 2
                        for i, line in enumerate(lines):
                            cv2.putText(annotated, line, (start_x + 5, current_y), font, font_scale, (255, 255, 255), thickness)
                            current_y += text_sizes[i][1] + line_spacing

            cv2.imshow("esp32 camera + inference", annotated)
          else:
            print("Warning: Failed to decode frame")

          key = cv2.waitKey(1) & 0xFF
          if key == ord('q'):
            raise KeyboardInterrupt # Break out of both loops
          elif key == ord('m'):
            print("\n--- Move Arm ---")
            try:
                x_str = input(f"Enter X (current: {current_pos[0]}): ")
                y_str = input(f"Enter Y (current: {current_pos[1]}): ")
                angle_str = input(f"Enter Angle (current: {current_gripper_angle}): ")
                
                if x_str.strip(): current_pos[0] = float(x_str)
                if y_str.strip(): current_pos[1] = float(y_str)
                if angle_str.strip(): current_gripper_angle = float(angle_str)
                
                print(f"Moving to {current_pos} with angle {current_gripper_angle}...")
                go_to_pos(current_pos, current_theta)
                set_gripper_rotation(current_gripper_angle)
            except ValueError:
                print("Invalid input. Please enter numbers.")
          elif key == ord('g'):
            if flipped is not None:
                filename = os.path.join("good", f"img_{int(time.time())}.jpg")
                cv2.imwrite(filename, flipped)
                good_count += 1
                print(f"Saved GOOD image: {filename} (Total: {good_count})")
          elif key == ord('b'):
            if flipped is not None:
                filename = os.path.join("bad", f"img_{int(time.time())}.jpg")
                cv2.imwrite(filename, flipped)
                bad_count += 1
                print(f"Saved BAD image: {filename} (Total: {bad_count})")
        
        conn.close()
    except KeyboardInterrupt:
      print("\nClosing program...")
    finally:
      print("Returning arm to rest position...")
      try:
          current_pos = [18.5, 0.0, 23.0]
          current_theta = -90.0
          print(f"Moving to starting position: {current_pos} with angle {current_theta}")
          go_to_pos(current_pos, current_theta)
          set_gripper_rotation(180)
      except Exception as e:
          print(f"Failed to rest arm: {e}")
      
      if 'server' in locals():
          server.close()
      cv2.destroyAllWindows()
      
      for label, xs in midpoints_x.items():
          if len(xs) > 0:
              avg_x = sum(xs) / len(xs)
              print(f"{label}: avg midpoint x = {avg_x: .1f} over {len(xs)} detections")

if __name__ == "__main__":
    main()
