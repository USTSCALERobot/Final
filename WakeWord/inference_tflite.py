import os
import sys

# Auto-re-execute using the virtual environment Python if not already running in it
base_dir = os.path.dirname(os.path.abspath(__file__))
venv_dir = os.path.abspath(os.path.join(base_dir, "venv"))
if os.path.exists(venv_dir) and os.path.abspath(sys.prefix) != venv_dir:
    venv_python = os.path.join(venv_dir, "bin", "python")
    if os.path.exists(venv_python):
        os.execv(venv_python, [venv_python] + sys.argv)

import sounddevice as sd
import numpy as np
import librosa
import time
import collections

# Attempt to load lightweight tflite_runtime first, fallback to standard tensorflow
try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:
    import tensorflow as tf
    Interpreter = tf.lite.Interpreter

# ==========================================
# Parameters
# ==========================================
FS = 16000          # 16 kHz sample rate
DURATION = 2.0      # 2 second audio chunks
N_MFCC = 32         # Number of MFCC bins
HOP_LENGTH = 512    # Hop length (512 over 32000 samples = 63 frames)
N_FFT = 2048        # FFT window size (Librosa default)
MODEL_PATH = "tflite_model/hey_dan_model.tflite"

print("Loading TFLite Wake Word model... This is very fast.")
try:
    interpreter = Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
except Exception as e:
    print(f"Error loading TFLite model: {e}")
    exit(1)

print("\nTFLite Model loaded successfully! 🚀")
print("Listening for wake word... (Press Ctrl+C to stop)")
print("="*50)

def process_audio(audio_data):
    """
    Takes 2 seconds of raw audio and converts it to MFCC features
    shaped exactly as the model expects: (1, 32, 63, 1)
    """
    # Flatten the audio into a 1D array
    audio_data = audio_data.flatten()
    
    target_len = int(FS * DURATION)
    # Ensure it's exactly target_len samples long
    if len(audio_data) < target_len:
        audio_data = np.pad(audio_data, (0, target_len - len(audio_data)), 'constant')
    else:
        audio_data = audio_data[:target_len]
        
    # Extract MFCCs using Librosa
    mfccs = librosa.feature.mfcc(
        y=audio_data, 
        sr=FS, 
        n_mfcc=N_MFCC, 
        n_fft=N_FFT, 
        hop_length=HOP_LENGTH
    )
    
    # Ensure time steps are exactly 63
    # If smaller, pad with zeros. If larger, truncate.
    if mfccs.shape[1] < 63:
        mfccs = np.pad(mfccs, ((0, 0), (0, 63 - mfccs.shape[1])), 'constant')
    else:
        mfccs = mfccs[:, :63]
        
    # Reshape to match the model's Input Layer: (Batch=1, Height=32, Width=63, Channels=1)
    mfccs = mfccs.reshape(1, N_MFCC, 63, 1)
    
    # Ensure it's float32 for TFLite
    return mfccs.astype(np.float32)

def main():
    # 2-second buffer at 16kHz = 32000 samples
    buffer_len = int(FS * DURATION)
    audio_buffer = collections.deque(maxlen=buffer_len)
    audio_buffer.extend(np.zeros(buffer_len))
    
    def audio_callback(indata, frames, time_info, status):
        """This is called for each audio block by sounddevice."""
        if status:
            print(status)
        # Add incoming audio to the right side of the rolling buffer
        audio_buffer.extend(indata[:, 0])
    print("\nWarming up audio processing (this takes a few seconds on a pi)...")
    _ = process_audio(np.zeros(buffer_len))
    print("Warmup Complete!!!")
    print("\nStarting continuous listening stream...")
    # Open a continuous audio stream
    with sd.InputStream(samplerate=FS, channels=1, dtype='float32', callback=audio_callback):
        while True:
            try:
                # 1. Grab a snapshot of the current 2-second buffer
                current_audio = np.array(audio_buffer)
                
                # 2. Process audio into features
                features = process_audio(current_audio)
                
                # 3. Run prediction via TFLite Interpreter
                interpreter.set_tensor(input_details[0]['index'], features)
                interpreter.invoke()
                prediction = interpreter.get_tensor(output_details[0]['index'])
                
                prob_wake_word = prediction[0][1]
                
                # 4. Print output based on confidence threshold
                if prob_wake_word >= 0.85:      # need to be 85% sure that this is "hey dan"
                    print(f">>> HELLO <<< (Confidence: {prob_wake_word:.2f})")
                    print("Wake word detected! Exiting to trigger STT.")
                    sys.exit(0)
                else:
                    # Use carriage return (\r) and end='' to update the same line and avoid console spam
                    print(f"\r... (Listening | Confidence: {prob_wake_word:.2f})    ", end="", flush=True)
                
                # Wait 200ms before predicting again.
                # This reduces the CPU load significantly while still keeping detection fast!
                time.sleep(0.10)
                
            except KeyboardInterrupt:
                print("\nStopped listening.")
                break

if __name__ == "__main__":
    main()
