import queue
import sounddevice as sd
import numpy as np
import soundfile as sf
import torch
from silero_vad import load_silero_vad, get_speech_timestamps

SAMPLE_RATE = 16000
CHANNELS = 1

# Silence timeout in seconds
SILENCE_DURATION = 1.2

# Audio chunk duration
BLOCK_DURATION = 0.5  # seconds

# Queue for audio chunks
audio_queue = queue.Queue()

# Load Silero VAD model
model = load_silero_vad()


def audio_callback(indata, frames, time, status):
    """
    Continuously receives microphone chunks.
    """

    if status:
        print(status)

    audio_queue.put(indata.copy())


def detect_speech(audio_chunk):
    """
    Returns True if speech detected.
    """

    audio_tensor = torch.tensor(
        audio_chunk.flatten(),
        dtype=torch.float32
    )

    speech_timestamps = get_speech_timestamps(
        audio_tensor,
        model,
        sampling_rate=SAMPLE_RATE
    )

    return len(speech_timestamps) > 0


def record_until_silence(output_file="recordings/input.wav"):

    # Clear old audio chunks
    while not audio_queue.empty():
        audio_queue.get()
        
    print("\nListening...\n")

    recorded_audio = []

    silence_counter = 0
    speech_started = False

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype='float32',
        blocksize=int(SAMPLE_RATE * BLOCK_DURATION),
        callback=audio_callback
    ):

        while True:
            
            audio_chunk = audio_queue.get()

            is_speaking = detect_speech(audio_chunk)

            # If speech detected
            if is_speaking:
                
                if not speech_started:
                    print("Speech detected. Recording...")

                speech_started = True

                silence_counter = 0

                recorded_audio.append(audio_chunk)

            else:

                # If already speaking before
                if speech_started:

                    recorded_audio.append(audio_chunk)

                    silence_counter += BLOCK_DURATION

                    print(f"Silence: {silence_counter:.1f}s")

                    # Stop if silence long enough
                    if silence_counter >= SILENCE_DURATION:
                        print("\nSpeech ended.\n")
                        break

    # Combine chunks
    final_audio = np.concatenate(recorded_audio, axis=0)

    # Save WAV
    sf.write(output_file, final_audio, SAMPLE_RATE)

    print(f"Saved audio to: {output_file}")

    return output_file