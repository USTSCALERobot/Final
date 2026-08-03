import socket
import struct
import cv2
import numpy as np

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

server.bind((HOST, PORT))
server.listen(1)
print("Waiting for esp...")
conn, addr = server.accept()
print("Connected:", addr)

while True:
  #read image length
  header = recv_all(conn,4)
  if not header:
    break
  size = struct.unpack("!I", header)[0]
  
  #read JPEG
  jpeg = recv_all(conn,size)
  img_array = np.frombuffer(jpeg, dtype=np.uint8)
  frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
  cv2.imshow("esp32 camera", frame)

  if cv2.waitKey(1)==27:
    break
