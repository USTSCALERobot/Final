#!/usr/bin/env python3
import tkinter as tk
import subprocess
import speech_recognition as sr
from difflib import SequenceMatcher
import os
import re

# Paths
SAVE_FOLDER    = "/home/scalepi/Desktop/savephototest"
VOSK_FILE      = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/vosk_voice_detection.py"
DETECTION_FILE = os.path.join(SAVE_FOLDER, "latest_detection.txt")
SPEECH_FILE    = os.path.join(SAVE_FOLDER, "speech_input.txt")
REQUEST_FILE   = os.path.join(SAVE_FOLDER, "chip_request_input.txt")
FLAG_PATH      = os.path.join(SAVE_FOLDER, "multi_capture.flag")

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

# def speech_to_text():
#     print("You have unlimited time to say chips, say next after each full chip and stop to end")
#     os.makedirs(SAVE_FOLDER, exist_ok=True)
#     #subprocess.run("arecord -D plughw:2,0 -d 6 UIRequestRecord.wav", shell=True)
#     #with sr.AudioFile('UIRequestRecord.wav') as source:
#         #audio = r.record(source)
#     result = subprocess.run(["python3", VOSK_FILE], capture_output=True, text=True)
#     text = result.stdout.strip()#r.recognize_google(audio)
#     print(f"You said: ", text)

#     # words = text.replace(",", " ").replace(" and ", " ").split()
#     # matched = []
#     # printed = set()
#     # for w in words:
#     #     best, best_score = None, 0.0
#     #     for p in KNOWN_PARTS:
#     #         s = SequenceMatcher(None, w.upper(), p.upper()).ratio()
#     #         if s > best_score:
#     #             best, best_score = p, s
#     #     if best and best_score >= 0.50 and best not in matched:
#     #         matched.append(best)
#     #         if best not in printed:
#     #             print(f"Matched: '{best}' (score: {best_score:.2f})")
#     #             printed.add(best)

#     # final_text = ", ".join(matched)
#     # print(f"\n Matched: {final_text}\n")
#     chip_id.delete(0, tk.END)
#     chip_id.insert(0, string=text)

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

def enable_large_selection():
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    with open(FLAG_PATH, "w") as f:
        f.write("1\n")
    print("🔵 Large-part selection ENABLED")

def disable_large_selection():
    try:
        os.remove(FLAG_PATH)
        print("⚪ Large-part selection DISABLED")
    except FileNotFoundError:
        print("⚪ Large-part selection already disabled")

# --- GUI ---
if __name__ == "__main__":
    chip_request = tk.Tk()
    chip_request.title("GUI Chip Request")
    chip_request.minsize(360, 240)

    tk.Label(text="Chip / Circuit Input").pack(pady=(8,2))
    chip_id = tk.Entry()
    chip_id.pack(fill="x", padx=10)

    tk.Button(chip_request, text="Speech to Text (Vosk)",   command=speech_to_text).pack(pady=3)
    tk.Button(chip_request, text="Submit Part Request",   command=save_input).pack(pady=3)
    tk.Button(chip_request, text="Submit Circuit Request",command=save_circuit_input).pack(pady=3)
    tk.Button(chip_request, text="Submit No Request",     command=save_no_input).pack(pady=3)
    tk.Button(chip_request, text="Load Previous Request", command=load_previous_request).pack(pady=3)

    tk.Label(text="Large-Part (two-frame) Mode").pack(pady=(10,2))
    tk.Button(chip_request, text="Large Part: ON",  command=enable_large_selection).pack(side="left", padx=10)
    tk.Button(chip_request, text="Large Part: OFF", command=disable_large_selection).pack(side="left")

    chip_request.mainloop()
