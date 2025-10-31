#!/usr/bin/env python3
import tkinter as tk
import subprocess
import speech_recognition as sr
from difflib import SequenceMatcher
import os
import re

# Paths
SAVE_FOLDER    = "/home/scalepi/Desktop/savephototest"
#SAVE_FOLDER    = "/home/scalepi/Desktop/savephototest"
DETECTION_FILE = os.path.join(SAVE_FOLDER, "latest_detection.txt")
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

def speech_to_text():
    print("You have 6 seconds to record chip characters…")
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    subprocess.run("arecord -D plughw:2,0 -d 6 UIRequestRecord.wav", shell=True)
    with sr.AudioFile('UIRequestRecord.wav') as source:
        audio = r.record(source)
    text = r.recognize_google(audio)
    print(f"\n🗣️ You said: {text}\n")

    words = text.replace(",", " ").replace(" and ", " ").split()
    matched = []
    printed = set()
    for w in words:
        best, best_score = None, 0.0
        for p in KNOWN_PARTS:
            s = SequenceMatcher(None, w.upper(), p.upper()).ratio()
            if s > best_score:
                best, best_score = p, s
        if best and best_score >= 0.50 and best not in matched:
            matched.append(best)
            if best not in printed:
                print(f"Matched: '{best}' (score: {best_score:.2f})")
                printed.add(best)

    final_text = ", ".join(matched)
    print(f"\n✅ Matched: {final_text}\n")
    chip_id.delete(0, tk.END)
    chip_id.insert(0, string=final_text)

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

    tk.Button(chip_request, text="Speech to Text (6s)",   command=speech_to_text).pack(pady=3)
    tk.Button(chip_request, text="Submit Part Request",   command=save_input).pack(pady=3)
    tk.Button(chip_request, text="Submit Circuit Request",command=save_circuit_input).pack(pady=3)
    tk.Button(chip_request, text="Submit No Request",     command=save_no_input).pack(pady=3)
    tk.Button(chip_request, text="Load Previous Request", command=load_previous_request).pack(pady=3)

    tk.Label(text="Large-Part (two-frame) Mode").pack(pady=(10,2))
    tk.Button(chip_request, text="Large Part: ON",  command=enable_large_selection).pack(side="left", padx=10)
    tk.Button(chip_request, text="Large Part: OFF", command=disable_large_selection).pack(side="left")

    chip_request.mainloop()
