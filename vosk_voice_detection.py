#!/usr/bin/env python3
import sounddevice as sd
import queue
import os
import json
import time
from vosk import Model, KaldiRecognizer
import string

SAVE_FOLDER = "/home/scalepi/Desktop/savephototest"
SPEECH_FILE = os.path.join(SAVE_FOLDER, "speech_input.txt")

# Configuration
LETTERS = list(string.ascii_lowercase)
WORDS = ["circuit"]
DIGITS = ["zero","one","two","three","four","five","six","seven","eight","nine"]
COMMANDS = ["next", "stop"]
KEYWORDS = LETTERS + DIGITS + COMMANDS + WORDS
DIGIT_MAP = {
    "zero":"0","one":"1","two":"2","three":"3","four":"4",
    "five":"5","six":"6","seven":"7","eight":"8","nine":"9"
}

# Queue for audio data
q = queue.Queue()

# Initialize Vosk
# Change path if your model folder is elsewhere (e.g., /home/pi/vosk-model-small-en-us-0.15)
model = Model("/home/scalepi/model")
rec = KaldiRecognizer(model, 16000, json.dumps(KEYWORDS))
rec.SetWords(True)

def combine_letters_and_digits(text: str) -> str:
    """Turn spaced letters/digits into a compact chip name (e.g. 's n 7 4 1 8 5 a n' → 'sn74185an')."""
    tokens = text.split()
    out = ""
    for tok in tokens:
        if tok in LETTERS:
            out += tok
        elif tok in DIGIT_MAP:
            out += DIGIT_MAP[tok]
        else:
            out += tok
    return out


def callback(indata, frames, time_info, status):
    """Sounddevice callback – queues audio chunks."""
    q.put(bytes(indata))

# Main Voice Capture Function
def run_voice_capture():
    chip_buffer = []
    current_phrase = []
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    # last_heard_time = time.time()
    # PHRASE_TIMEOUT = 2.0  # seconds between tokens before committing a phrase

    with sd.RawInputStream(samplerate=16000, blocksize=8000,
                           dtype='int16', channels=1, callback=callback):
        print("-" * 40)
        print("Listening... Say chip names, 'next' for comma, 'stop' to finish.")
        print("-" * 40)

        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get("text", "").lower().strip()
                if not text:
                    continue

                now = time.time()

                # # --- Handle control commands ---
                # if text == "next":
                #     # combine the current phrase before adding comma
                #     if current_phrase:
                #         combined = combine_letters_and_digits(" ".join(current_phrase))
                #         chip_buffer.append(combined)
                #         current_phrase = []
                #     chip_buffer.append(",")
                #     print("Next chip.")
                #     continue

                # elif text == "stop":
                #     # finalize any remaining phrase
                #     if current_phrase:
                #         combined = combine_letters_and_digits(" ".join(current_phrase))
                #         chip_buffer.append(combined)
                #     print("Stopping capture.")
                #     break

                # # --- Regular letter/digit input ---
                # # only commit previous phrase if enough time passed AND the new token isn't 'stop'
                # if (now - last_heard_time > PHRASE_TIMEOUT) and (text != "stop"):
                #     if current_phrase:
                #         combined = combine_letters_and_digits(" ".join(current_phrase))
                #         chip_buffer.append(combined)
                #         current_phrase = []

                # current_phrase.append(text)
                # last_heard_time = now

                # print("Heard:", text)
                # print("Partial phrase:", " ".join(current_phrase))
                # print("Buffer so far:", " ".join(chip_buffer))
                # print("-" * 40)
                # --- Handle control and input words ---
                if text in ["next", "stop"]:
                    # Combine the current phrase when "next" or "stop" is spoken
                    if current_phrase:
                        combined = combine_letters_and_digits(" ".join(current_phrase))
                        chip_buffer.append(combined)
                        current_phrase = []

                    if text == "next":
                        chip_buffer.append(",")
                        print("Next chip.")
                        print("-" * 40)
                        continue

                    elif text == "stop":
                        print("Stopping capture.")
                        print("-" * 40)
                        break
                else:
                    # Accumulate normal letters/digits
                    current_phrase.append(text)

                # Debugging / display (optional)
                print("Heard:", text)
                print("Partial phrase:", " ".join(current_phrase))
                print("Buffer so far:", " ".join(chip_buffer))
                print("-" * 40)

    # # finalize leftover phrase
    # if current_phrase:
    #     combined = combine_letters_and_digits(" ".join(current_phrase))
    #     chip_buffer.append(combined)

    final_string = " ".join(chip_buffer).replace(" ,", ",")
    print(f"Final detected chips: {final_string}")

    # === Save recognized chips for the GUI ===
    try:
        with open(SPEECH_FILE, "w") as f:
            f.write(final_string.strip() + "\n")
        print(f"Saved recognized chips to {SPEECH_FILE}")
    except Exception as e:
        print(f"Could not save to {SPEECH_FILE}: {e}")
    print("-" * 40)
    return final_string

# Run if executed directly
if __name__ == "__main__":
    run_voice_capture()