import socket
import struct
import cv2
import numpy as np

#"10.42.0.1"
HOST = "10.42.0.1"
PORT = 5000

def recv_all(sock, size):
  data = b""
  while len(data)<size:
    packet = sock.recv(size-len(data))
    if not packet:
      return None
    data += packet
  return data

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(1)

while True:
  print("Waiting for esp...")
  conn, addr = server.accept()
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
    flipped = cv2.rotate(frame,cv2.ROTATE_180)
    if frame is not None:
      cv2.imshow("esp32 camera", flipped)
    else:
      print("Warning: Failed to decode frame")

    if cv2.waitKey(1)==ord('q'):
      break
  
  conn.close()
  if cv2.waitKey(1)==ord('q'):
    break
