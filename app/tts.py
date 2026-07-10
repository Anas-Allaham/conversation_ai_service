# This:
# sends AI response to OpenAI TTS
# saves mp3

import subprocess
import os
import uuid

PIPER_PATH = r"piper\piper.exe"
MODEL_PATH = r"models\en_US-lessac-medium.onnx"

def text_to_speech(text):

    for file in os.listdir("outputs"):
        if file.endswith(".wav"):
            try:
                os.remove(
                    os.path.join(
                        "outputs",
                        file
                    )
                )
            except:
                pass

    os.makedirs(
        "outputs",
        exist_ok=True
    )

    output_file = f"outputs/{uuid.uuid4()}.wav"

    print("Generating speech with Piper...")

    command = [
        PIPER_PATH,
        "--model",
        MODEL_PATH,
        "--output_file",
        output_file
    ]

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE
    )

    process.communicate(
        input=text.encode("utf-8")
    )

    print(f"Speech saved to: {output_file}")

    return output_file