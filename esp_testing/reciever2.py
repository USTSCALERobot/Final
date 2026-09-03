import argparse
import socket
import struct
import cv2
import numpy as np
import sys
import os
import shlex
import time
import threading
from pathlib import Path
from ultralytics import YOLO
from collections import defaultdict

# Add phx_articulate2 to path so we can import kinematics and phx
phx_dir = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/phx_articulate2"
if phx_dir not in sys.path:
   sys.path.append(phx_dir)
import kinematics as kin
import phx

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
'''
Pulls raw data from the ESP32 and ensures full image is recieved before decoding
'''
def recv_all(sock, size):
  data = b""
  while len(data)<size:
    packet = sock.recv(size-len(data))
    # if no data is recieved, return None to prevent crashes
    if not packet:
      return None
    data += packet  # adds packet to data until full image is recieved 
  return data

class LatestFrame:
    def __init__(self):
        self.frame = None
        self.lock = threading.Lock()
        self.running = True

    def get(self):
        with self.lock:
            return self.frame

    def set(self, frame):
        with self.lock:
            self.frame = frame

def receiver_thread(conn, latest_frame):
    while latest_frame.running:
        #read image length
        header = recv_all(conn,4)
        if not header:
            print("Connection closed by ESP32")
            latest_frame.running = False
            break
        size = struct.unpack("!I", header)[0]
        
        #read JPEG
        jpeg = recv_all(conn,size)
        if not jpeg:
            print("Connection closed by ESP32 during frame")
            latest_frame.running = False
            break
        img_array = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        flipped = cv2.rotate(frame, cv2.ROTATE_180)
        latest_frame.set(flipped)

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
   scaled_angle = 180 + (ang_deg * 1.2)
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


    # Initialize arm
    print("Initializing robot arm...")
    phx.turn_on()
    current_pos = [18.5, 0.0, 23.0]
    current_theta = -90.0
    current_gripper_angle = 0.0
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

    try:
      while True:
        try:
          conn, addr = server.accept()
        except socket.timeout:
          continue # Timeout reached, loop back to check for KeyboardInterrupt
          
        print("Connected:", addr)
        
        latest_frame = LatestFrame()
        t = threading.Thread(target=receiver_thread, args=(conn, latest_frame))
        t.daemon = True
        t.start()

        while latest_frame.running:
          flipped = latest_frame.get()
          
          if flipped is not None:
            target_x = None
            target_y = None
            target_r_deg = None
            
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
                        
                        if target_x is None and target_y is None:
                            target_x = cx
                            target_y = cy
                            target_r_deg = 90 - np.degrees(r)
                        
                        # Convert rotation from radians to degrees
                        r_deg = 90 - np.degrees(r)

                        # Create custom label lines (removed class name)
                        lines = [
                            f"Mid: ({cx:.1f}, {cy:.1f})",
                            f"Rot: {r_deg:.1f}deg"
                        ]
                        
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = 0.25
                        thickness = 1
                        line_spacing = 4
                        
                        # Calculate dimensions
                        text_sizes = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in lines]
                        max_w = max([size[0] for size in text_sizes])
                        total_h = sum([size[1] + line_spacing for size in text_sizes])
                        
                        # Find top right corner of OBB
                        top_right_x = int(np.max(corner[:, 0]))
                        top_right_y = int(np.min(corner[:, 1]))
                        
                        # 20px buffer from top right
                        start_x = top_right_x + 20
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
                        mid_y = (y1 + y2) / 2
                        
                        if target_x is None and target_y is None:
                            target_x = mid_x
                            target_y = mid_y
                        
                        lines = [
                            f"Conf: {c:.2f}",
                            f"Mid: ({mid_x:.1f}, {(y1+y2)/2:.1f})"
                        ]
                        
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = 0.25
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
            
            #########################################################################################################
            # Conditional movement based on target_x and target_y
            # moves 2.5mm per frame per direction
            # rotation angle option to adjust for angle offsets. 
            if target_x is not None and target_y is not None and target_r_deg is not None:
                
                if target_x < 325:
                  current_pos[1] = current_pos[1] - 0.1  # we move arm in the y-direction here as the plane is inverted
                elif target_x > 335:
                  current_pos[1] = current_pos[1] + 0.1  
                if target_y < 360:
                  current_pos[0] = current_pos[0] + 0.1 
                elif target_y > 380:
                  current_pos[0] = current_pos[0] - 0.1    
                #go_to_pos(current_pos, current_theta)
                if r_deg > 2:       
                  current_gripper_angle = current_gripper_angle +1
                elif r_deg < -2: 
                   current_gripper_angle = current_gripper_angle -1
                go_to_pos(current_pos, current_theta)
                set_gripper_rotation(current_gripper_angle)
            ########################################################################################################## 
          else:
            time.sleep(0.01) # Wait for first frame or next frame
        
          key = cv2.waitKey(1) & 0xFF
          if key == ord('q'):
            latest_frame.running = False
            raise KeyboardInterrupt # Break out of both loops
          
        
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
          set_gripper_rotation(0)
      except Exception as e:
          print(f"Failed to rest arm: {e}")
      
      if 'server' in locals():
          server.close()
      cv2.destroyAllWindows()
      

if __name__ == "__main__":
    main()
