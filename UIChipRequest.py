import tkinter as tk
from tkinter import messagebox
import subprocess
import speech_recognition as sr
from difflib import SequenceMatcher

r = sr.Recognizer()

KNOWN_PARTS = [
    "P8436 DM74S240N", "SN74LS5IN M18034",
    "LM745", "SN74185AN", "SN7414N",
    "M73AF LF 356BN", "DM7414N", "CIRCUIT1, CIRCUIT2"
]

DETECTION_FILE = "/home/scalepi/Desktop/savephototest/latest_detection.txt"
VOSK_FILE = "/home/scalepi/hailo-rpi5-examples/basic_pipelines/Final/vosk_voice_detection.py"

def save_input():
    chip = chip_id.get()
    if chip.strip():
        with open("/home/scalepi/Desktop/savephototest/chip_request_input.txt", "w") as file:
               file.write(f"Requested Part: {chip}")
        print("Chip Request Input Saved Successfully!")
        chip_request.destroy()
    else:
        print("Chip Request Failed")

def save_circuit_input():
    chip = chip_id.get()
    if chip.strip():
        with open("/home/scalepi/Desktop/savephototest/chip_request_input.txt", "w") as file:
               file.write(f"Requested Circuit: {chip}")
        print("Circuit Request Input Saved Successfully!")
        chip_request.destroy()
    else:
        print("Circuit Request Failed")

def save_no_input():
    chip = "None"
    with open("/home/scalepi/Desktop/savephototest/chip_request_input.txt", "w") as file:
        file.write(f"Requested Part: {chip}")
    print("No Requested Item Input Saved Successfully!")
    chip_request.destroy()

def speech_to_text():
    print("You have 6 seconds to record chip characters")
    subprocess.run("arecord -D plughw:2,0 -d 6 UIRequestRecord.wav", shell=True)
    chip_speech = sr.AudioFile('UIRequestRecord.wav')
    with chip_speech as source:
        audio = r.record(source)
    translated_audio = r.recognize_google(audio)
    
    print(f"\n🗣️ You said: {translated_audio}\n")

    words = translated_audio.replace(",", " ").replace(" and ", " ").split()
    matched_parts = []
    printed_parts = set()

    for word in words:
        best_score = 0.0
        best_match = None
        for part in KNOWN_PARTS:
            score = SequenceMatcher(None, word.upper(), part.upper()).ratio()
            if score > best_score:
                best_score = score
                best_match = part
        if best_match and best_score >= 0.50 and best_match not in matched_parts:
            matched_parts.append(best_match)
            if best_match not in printed_parts:
                print(f"🔎 Matched: '{best_match}' (score: {best_score:.2f})")
                printed_parts.add(best_match)

    final_text = ", ".join(matched_parts)
    print(f"\n✅ Matched parts: {final_text}\n")

    chip_id.delete(0, tk.END)
    chip_id.insert(0, string=final_text)

def load_previous_request():
    try:
        with open(DETECTION_FILE, 'r') as file:
            lines = file.readlines()
        # reverse search to find the most recent request
        for line in reversed(lines):
            if line.startswith("6. Requested Part(s):"):
                previous = line.split(":", 1)[1].strip()
                chip_id.delete(0, tk.END)
                chip_id.insert(0, string=previous)
                print(f"↩️ Loaded previous request: {previous}")
                return
        print("⚠️ No previous request found in detection file.")
    except Exception as e:
        print(f"❌ Error loading previous request: {e}")

# --- GUI Setup ---
if __name__ == "__main__":
    chip_request = tk.Tk()
    chip_request.title("GUI Chip Request")
    chip_request.minsize(358, 220)

    chip_char = tk.Label(text="Chip ID Character(s)").pack()
    chip_id = tk.Entry()
    chip_id.pack()
    tk.Button(chip_request, text="Speech to Text (6s)",   command=speech_to_text).pack()
    tk.Button(chip_request, text="Submit Part Request",   command=save_input).pack()
    tk.Button(chip_request, text="Submit Circuit Request",command=save_circuit_input).pack()
    tk.Button(chip_request, text="Submit No Request",     command=save_no_input).pack()
    tk.Button(chip_request, text="Load Previous Request", command=load_previous_request).pack()

    chip_request.mainloop()
