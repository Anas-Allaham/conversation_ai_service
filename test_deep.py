import httpx
import threading

from deepgram import DeepgramClient
from deepgram.core.events import EventType

DEEPGRAM_API_KEY = "a0baa0715d56e056580b7880c3d438d405a0bd40"

# Note: This is an English stream, update accordingly for other languages
STREAM_URL = "https://playerservices.streamtheworld.com/api/livestream-redirect/CSPANRADIOAAC.aac"

client = DeepgramClient(api_key=DEEPGRAM_API_KEY)

with client.listen.v1.connect(
    model="nova-3",
    language="en",
) as connection:
    ready = threading.Event()

    def on_message(result):
        event_type = result.type
        if event_type == "Results":
            channel = result.channel
            alt = channel.alternatives[0]
            transcript = alt.transcript
            if transcript:
                print(transcript)

    connection.on(EventType.OPEN, lambda _: ready.set())
    connection.on(EventType.MESSAGE, on_message)

    def stream():
        ready.wait()
        with httpx.stream("GET", STREAM_URL, follow_redirects=True) as response:
            for chunk in response.iter_bytes():
                connection.send_media(chunk)

    threading.Thread(target=stream, daemon=True).start()

    print(f"Transcribing {STREAM_URL}...")
    connection.start_listening()