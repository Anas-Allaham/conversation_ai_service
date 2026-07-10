import queue
from app.player import is_playing
import time

import numpy as np
import sounddevice as sd
import soundfile as sf
import torch

from silero_vad import (
    load_silero_vad,
    get_speech_timestamps
)


# ==========================
# CONFIG
# ==========================

SAMPLE_RATE = 16000
BLOCK_DURATION = 0.5

IGNORE_SECONDS = 3       # ignore first seconds of AI playback
ENERGY_THRESHOLD = 0.05  # louder = harder to trigger
MAX_SILENCE = 1.5        # interruption recording stops after silence


# ==========================
# GLOBALS
# ==========================

audio_queue = queue.Queue()

model = load_silero_vad()


# ==========================
# CALLBACK
# ==========================

def callback(
        indata,
        frames,
        time_info,
        status):

    if status:
        print(status)

    audio_queue.put(
        indata.copy()
    )


# ==========================
# QUEUE CLEANER
# ==========================

def clear_audio_queue():

    while not audio_queue.empty():

        try:

            audio_queue.get_nowait()

        except queue.Empty:

            break


# ==========================
# INTERRUPTION DETECTOR
# ==========================

def detect_interruption(

        ignore_seconds=IGNORE_SECONDS

):

    print(

        "Monitoring interruptions..."

    )


    clear_audio_queue()


    start = time.time()


    with sd.InputStream(

        samplerate=SAMPLE_RATE,

        channels=1,

        dtype="float32",

        blocksize=int(

            SAMPLE_RATE *

            BLOCK_DURATION

        ),

        callback=callback

    ):


        while True:


            # NEW
            if not is_playing():

                return False


            try:

                chunk = audio_queue.get(

                    timeout=0.2

                )


            except queue.Empty:

                continue


            elapsed = (

                time.time()

                -

                start

            )


            if elapsed < ignore_seconds:

                continue


            tensor = torch.tensor(

                chunk.flatten(),

                dtype=torch.float32

            )


            speech = get_speech_timestamps(

                tensor,

                model,

                sampling_rate=SAMPLE_RATE

            )


            mic_energy = np.mean(

                np.abs(chunk)

            )


            if (

                len(speech) > 0

                and

                mic_energy >

                ENERGY_THRESHOLD

            ):


                print(

                    "INTERRUPTION"

                )


                return True
# ==========================
# INTERRUPTION RECORDER
# ==========================

def capture_interruption():

    print(

        "Capturing interruption..."

    )

    clear_audio_queue()

    recorded = []

    silence = 0


    with sd.InputStream(

        samplerate=SAMPLE_RATE,

        channels=1,

        dtype="float32",

        blocksize=int(
            SAMPLE_RATE *
            BLOCK_DURATION
        ),

        callback=callback

    ):

        while True:

            try:

                chunk = audio_queue.get(
                    timeout=1
                )

            except queue.Empty:

                continue


            tensor = torch.tensor(

                chunk.flatten(),

                dtype=torch.float32

            )


            speech = get_speech_timestamps(

                tensor,

                model,

                sampling_rate=SAMPLE_RATE

            )


            if len(speech) > 0:

                silence = 0

            else:

                silence += BLOCK_DURATION


            recorded.append(
                chunk
            )


            if silence >= MAX_SILENCE:

                break


    # Empty recording protection
    if len(recorded) == 0:

        print(

            "No interruption captured"

        )

        return None


    audio = np.concatenate(

        recorded,

        axis=0

    )


    path = (

        "recordings/interruption.wav"

    )


    sf.write(

        path,

        audio,

        SAMPLE_RATE

    )


    print(

        f"Saved interruption: {path}"

    )


    return path