# wha will do?
# This records microphone audio
# # 1. Listen to microphone
# 2. Record audio
# 3. Save WAV file

import sounddevice as sd
from scipy.io.wavfile import write
import os

# Audio settings
SAMPLE_RATE = 16000
DURATION = 5  # seconds

def record_audio(filename="recordings/input.wav"):
    """
    Records audio from microphone and saves as WAV file.
    """

    print("Listening... S peak now.")

    # Record audio
    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='int16'
    )

    sd.wait()

    print("Recording finished.")

    # Create recordings folder if missing
    os.makedirs("recordings", exist_ok=True)

    # Save WAV file
    write(filename, SAMPLE_RATE, audio)

    print(f"Audio saved to: {filename}")

    return filename