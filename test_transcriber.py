from app.transcriber import transcribe_audio

text = transcribe_audio("recordings/input.wav")

print(text)