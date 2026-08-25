import socket
import struct
import cv2
import numpy as np
import sys
import os
import time

# Add phx_articulate2 to path so we can import kinematics and phx
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'phx_articulate2')))
import kinematics as kin
import phx

#"10.42.0.1"
HOST = "10.42.0.1"
PORT = 5000

# Create folders for saving images
os.makedirs("good", exist_ok=True)
os.makedirs("bad", exist_ok=True)
good_count = 0
bad_count = 0

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

# Initialize arm
print("Initializing robot arm...")
phx.turn_on()
phx.rest_position()
current_pos = [18.5, 0.0, 23.0]
current_theta = -90.0
print(f"Moving to starting position: {current_pos} with angle {current_theta}")
go_to_pos(current_pos, current_theta)

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(1)
server.settimeout(1.0) # Allow accept() to timeout so we can catch Ctrl+C

print(f"Listening on {HOST}:{PORT}. Press Ctrl+C or 'q' in the video window to exit.")

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
      
      if frame is not None:
        cv2.imshow("esp32 camera", frame)
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
            z_str = input(f"Enter Z (current: {current_pos[2]}): ")
            theta_str = input(f"Enter Angle (current: {current_theta}): ")
            
            if x_str.strip(): current_pos[0] = float(x_str)
            if y_str.strip(): current_pos[1] = float(y_str)
            if z_str.strip(): current_pos[2] = float(z_str)
            if theta_str.strip(): current_theta = float(theta_str)
            
            print(f"Moving to {current_pos} with angle {current_theta}...")
            go_to_pos(current_pos, current_theta)
        except ValueError:
            print("Invalid input. Please enter numbers.")
      elif key == ord('g'):
        if frame is not None:
            filename = os.path.join("good", f"img_{int(time.time())}.jpg")
            cv2.imwrite(filename, frame)
            good_count += 1
            print(f"Saved GOOD image: {filename} (Total: {good_count})")
      elif key == ord('b'):
        if frame is not None:
            filename = os.path.join("bad", f"img_{int(time.time())}.jpg")
            cv2.imwrite(filename, frame)
            bad_count += 1
            print(f"Saved BAD image: {filename} (Total: {bad_count})")
    
    conn.close()
except KeyboardInterrupt:
  print("\nClosing program...")
finally:
  print("Returning arm to rest position...")
  try:
      phx.rest_position()
  except Exception as e:
      print(f"Failed to rest arm: {e}")
  server.close()
  cv2.destroyAllWindows()
