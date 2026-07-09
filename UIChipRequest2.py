#!/usr/bin/env python3
import tkinter as tk
import subprocess
import speech_recognition as sr
from difflib import SequenceMatcher
import os
import re
import threading
import time

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

r = sr.Recognizer()

def _write_request(kind: str, value: str):
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    with open(REQUEST_FILE, "w") as f:
        f.write(f"Requested {kind}: {value}")
    print(f"Saved -> Requested {kind}: {value}")

def save_input():
    txt = chip_id.get().strip()
    if txt:
        _write_request("Part", txt)
        chip_request.destroy()
    else:
        print("Chip Request Failed (empty)")

def save_circuit_input():
    txt = chip_id.get().strip()
    if txt:
        _write_request("Circuit", txt)
        chip_request.destroy()
    else:
        print("Circuit Request Failed (empty)")

def save_no_input():
    _write_request("Part", "None")
    chip_request.destroy()


def speech_to_text():
    print("🎙️ Running Vosk voice recognition...")
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

def _update_ui(recognized):
    chip_id.delete(0, tk.END)
    chip_id.insert(0, recognized)
    print(f"✅ Loaded recognized chips: {recognized}")

def background_wakeword_loop():
    WAKEWORD_FILE = "/home/teddy/Desktop/Final/WakeWord/inference_tflite.py"
    while True:
        print("\n🎧 Waiting for wake word...")
        try:
            # Block until the wakeword script exits (which it will when it hears the wakeword)
            result = subprocess.run(["python3", WAKEWORD_FILE])
            if result.returncode == 0:
                print("✨ Wake word detected! Triggering STT in background...")
                # Run Vosk directly here
                subprocess.run(["python3", VOSK_FILE], check=True)
                
                # Now read the recognized text
                if os.path.exists(SPEECH_FILE):
                    with open(SPEECH_FILE, 'r') as f:
                        recognized = f.read().strip()
                    if recognized:
                        # Safely update UI from the background thread via after()
                        chip_request.after(0, lambda r=recognized: _update_ui(r))
                    else:
                        print("⚠️ No recognized text found in speech file.")
                else:
                    print(f"Speech file not found at {SPEECH_FILE}")
            else:
                # If script exited with non-zero, it likely crashed or was interrupted.
                time.sleep(2)
        except Exception as e:
            print(f"Background loop error: {e}")
            time.sleep(2)


# --- GUI ---
if __name__ == "__main__":
    chip_request = tk.Tk()
    chip_request.title("GUI Chip Request")
    chip_request.minsize(360, 240)

    # Start the continuous wake word + STT state machine
    threading.Thread(target=background_wakeword_loop, daemon=True).start()

    tk.Label(text="Chip / Circuit Input").pack(pady=(8,2))
    chip_id = tk.Entry()
    chip_id.pack(fill="x", padx=10)

    tk.Button(chip_request, text="Speech to Text (Vosk)",   command=speech_to_text).pack(pady=3)
    tk.Button(chip_request, text="Submit Part Request",   command=save_input).pack(pady=3)
    tk.Button(chip_request, text="Submit Circuit Request",command=save_circuit_input).pack(pady=3)
    tk.Button(chip_request, text="Submit No Request",     command=save_no_input).pack(pady=3)
    tk.Button(chip_request, text="Load Previous Request", command=load_previous_request).pack(pady=3)



    chip_request.mainloop()
