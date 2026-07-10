from app.tts import text_to_speech
from app.player import (
    play_audio,
    is_playing
)

audio = text_to_speech(
    "Hello this is a long test"
)

play_audio(audio)

while True:

    print(
        is_playing()
    )