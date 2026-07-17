#!/usr/bin/env python3
import tkinter as tk
import subprocess
import speech_recognition as sr
from difflib import SequenceMatcher
import os
import re
import threading
import time
import collections
import numpy as np
import librosa
import sounddevice as sd

try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:
    import tensorflow as tf
    Interpreter = tf.lite.Interpreter

# Paths
SAVE_FOLDER    = "/home/scalepi/Desktop/savephototest"
VOSK_FILE      = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/vosk_voice_detection.py"
DETECTION_FILE = os.path.join(SAVE_FOLDER, "latest_detection.txt")
SPEECH_FILE    = os.path.join(SAVE_FOLDER, "speech_input.txt")
REQUEST_FILE   = os.path.join(SAVE_FOLDER, "chip_request_input.txt")

# Known parts and circuits for STT matching
KNOWN_PARTS = [
    "P8436 DM74S240N", "SN74LS5IN M18034",
    "LM745", "SN74185AN", "SN7414N",
    "M73AF LF 356BN", "DM7414N",
    "CIRCUIT1", "CIRCUIT2"
]

# Wake Word Parameters
FS = 16000
DURATION = 2.0
N_MFCC = 32
HOP_LENGTH = 512
N_FFT = 2048
WAKE_MODEL_PATH = "/home/scalepi/Desktop/tflite_model/hey_dan_model.tflite" # Change this to the path on the Pi
STOP_LISTENING = False

def process_audio(audio_data):
    audio_data = audio_data.flatten()
    target_len = int(FS * DURATION)
    if len(audio_data) < target_len:
        audio_data = np.pad(audio_data, (0, target_len - len(audio_data)), 'constant')
    else:
        audio_data = audio_data[:target_len]
        
    mfccs = librosa.feature.mfcc(
        y=audio_data, sr=FS, n_mfcc=N_MFCC, n_fft=N_FFT, hop_length=HOP_LENGTH
    )
    if mfccs.shape[1] < 63:
        mfccs = np.pad(mfccs, ((0, 0), (0, 63 - mfccs.shape[1])), 'constant')
    else:
        mfccs = mfccs[:, :63]
    return mfccs.reshape(1, N_MFCC, 63, 1).astype(np.float32)

def wake_word_listener(gui_root):
    print("Loading TFLite Wake Word model...")
    try:
        interpreter = Interpreter(model_path=WAKE_MODEL_PATH)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
    except Exception as e:
        print(f"Error loading TFLite model (Path: {WAKE_MODEL_PATH}): {e}")
        return

    buffer_len = int(FS * DURATION)
    audio_buffer = collections.deque(maxlen=buffer_len)
    audio_buffer.extend(np.zeros(buffer_len))
    
    def audio_callback(indata, frames, time_info, status):
        if status:
            pass # Ignore status spam
        audio_buffer.extend(indata[:, 0])

    print("Warming up audio processing...")
    _ = process_audio(np.zeros(buffer_len))
    
    print("Listening for wake word...")
    with sd.InputStream(samplerate=FS, channels=1, dtype='float32', callback=audio_callback):
        while True:
            global STOP_LISTENING
            if STOP_LISTENING:
                print("GUI closed. Stopping wake word listener cleanly...")
                break
                
            try:
                current_audio = np.array(audio_buffer)
                features = process_audio(current_audio)
                
                interpreter.set_tensor(input_details[0]['index'], features)
                interpreter.invoke()
                prediction = interpreter.get_tensor(output_details[0]['index'])
                
                prob_wake_word = prediction[0][1]
                
                if prob_wake_word >= 0.70:
                    print(f"\n>>> WAKE WORD DETECTED <<< (Confidence: {prob_wake_word:.2f})")
                    # Trigger the GUI event
                    try:
                        gui_root.event_generate("<<WakeWordDetected>>", when="tail")
                    except Exception:
                        pass
                    break # Exit loop, release mic!
                else:
                    # Provide visual proof that the thread is looping ~10x a second
                    print(f"\r... (Listening | Confidence: {prob_wake_word:.2f})    ", end="", flush=True)
                
                time.sleep(0.1)
            except Exception as e:
                print(f"Listener error: {e}")
                break
    print("Wake word thread dying, mic released.")

r = sr.Recognizer()

def _write_request(kind: str, value: str):
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    with open(REQUEST_FILE, "w") as f:
        f.write(f"Requested {kind}: {value}")
    print(f"Saved -> Requested {kind}: {value}")

def close_gui():
    global STOP_LISTENING
    STOP_LISTENING = True
    chip_request.destroy()

def save_input():
    txt = chip_id.get().strip()
    if txt:
        _write_request("Part", txt)
        close_gui()
    else:
        print("Chip Request Failed (empty)")

def save_circuit_input():
    txt = chip_id.get().strip()
    if txt:
        _write_request("Circuit", txt)
        close_gui()
    else:
        print("Circuit Request Failed (empty)")

def save_no_input():
    _write_request("Part", "None")
    close_gui()


def speech_to_text():
 
    print("🎙️ Running Vosk voice recognition...")

    if 'listener_thread' in globals() and listener_thread.is_alive():
        listener_thread.join(timeout=1)
    try:
        # Run the Vosk script and wait for it to finish
        subprocess.run(["python3", VOSK_FILE], check=True)

        # Now read the recognized text from the shared file
        with open(SPEECH_FILE, 'r') as f:
            recognized = f.read().strip()

        if recognized:
            chip_id.delete(0, tk.END)
            chip_id.insert(0, recognized)
            print(f"✅ Loaded recognized chips: {recognized}")
        else:
            print("⚠️ No recognized text found in speech file.")
            
    except FileNotFoundError:
        print(f"Speech file not found at {SPEECH_FILE}")
    except subprocess.CalledProcessError as e:
        print(f"Vosk script exited with an error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    

def load_previous_request():
    try:
        with open(DETECTION_FILE, 'r') as f:
            lines = f.readlines()
        for line in reversed(lines):
            m = re.search(r"^\s*(?:6\.\s*)?Requested Part\(s\):\s*(.+)$", line)
            if m:
                prev = m.group(1).strip()
                chip_id.delete(0, tk.END)
                chip_id.insert(0, string=prev)
                print(f"↩️ Loaded previous request: {prev}")
                return
        print("No previous request found in detection file.")
    except Exception as e:
        print(f"Error loading previous request: {e}")


def on_wakeword_detected(event):
    dan_listen.config(text="Hello, waiting for command", background="Green")
    dan_listen.update()

    print("GUI received wake-word signal. Launching Vosk...")
   #
    speech_to_text()

# --- GUI ---
if __name__ == "__main__":
    chip_request = tk.Tk()
    chip_request.title("GUI Chip Request")
    chip_request.minsize(360, 240)
    
    chip_request.protocol("WM_DELETE_WINDOW", close_gui)
    chip_request.bind("<<WakeWordDetected>>", on_wakeword_detected)
    
    # Start the listening thread automatically
    listener_thread = threading.Thread(target=wake_word_listener, args=(chip_request,), daemon=True)
    listener_thread.start()
    
    tk.Label(text="Chip / Circuit Input").pack(pady=(8,2))
    chip_id = tk.Entry()
    chip_id.pack(fill="x", padx=10)
    dan_listen = tk.Label(text="Listening for Hey Dan",background="red")
    dan_listen.pack(pady= 3)
    tk.Button(chip_request, text="Speech to Text (Vosk)",   command=speech_to_text).pack(pady=3)
    tk.Button(chip_request, text="Submit Part Request",   command=save_input).pack(pady=3)
    tk.Button(chip_request, text="Submit Circuit Request",command=save_circuit_input).pack(pady=3)
    tk.Button(chip_request, text="Submit No Request",     command=save_no_input).pack(pady=3)
    tk.Button(chip_request, text="Load Previous Request", command=load_previous_request).pack(pady=3)



    chip_request.mainloop()
    if 'listener_thread' in globals() and listener_thread.is_alive():
        listener_thread.join(timeout=1)