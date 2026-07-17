from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Sequence

import sounddevice as sd
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from dotenv import load_dotenv


SAMPLE_RATE = 16_000
CHANNELS = 1
CHUNK_MS = 80
BLOCK_SIZE = SAMPLE_RATE * CHUNK_MS // 1_000


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read a field from either an SDK model or a plain dictionary."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _text_value(value: Any) -> str:
    """Normalize SDK literals/enums/strings to a comparable string."""
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


@dataclass(frozen=True, slots=True)
class FluxTurn:
    text: str
    turn_index: int
    average_word_confidence: float
    end_of_turn_confidence: float
    audio_window_start: float
    audio_window_end: float
    low_confidence_words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FluxEvent:
    """Conversation-level event emitted by Flux."""

    kind: str
    transcript: str
    turn_index: int
    turn: FluxTurn | None = None


class DeepgramFluxASR:
    """Persistent microphone -> Deepgram Flux streaming ASR service."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        input_device: int | str | None = None,
        eot_threshold: float = 0.80,
        eot_timeout_ms: int = 7_000,
        keyterms: Sequence[str] | None = None,
        queue_seconds: int = 5,
    ) -> None:
        load_dotenv()

        resolved_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "DEEPGRAM_API_KEY is missing. Add it to the project .env file."
            )

        self._client = AsyncDeepgramClient(api_key=resolved_key)
        self._input_device = input_device
        self._eot_threshold = eot_threshold
        self._eot_timeout_ms = eot_timeout_ms
        self._keyterms = list(keyterms or ())

        chunks_per_second = max(1, 1_000 // CHUNK_MS)
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=max(10, queue_seconds * chunks_per_second)
        )
        # Finalized turns are kept for backwards compatibility and
        # pronunciation-analysis consumers.
        self.turns: asyncio.Queue[FluxTurn] = asyncio.Queue()

        # The session controller consumes StartOfTurn/TurnResumed/
        # EagerEndOfTurn/EndOfTurn from this queue.
        self.events: asyncio.Queue[FluxEvent] = asyncio.Queue()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._microphone: sd.RawInputStream | None = None
        self._last_partial = ""
        self._dropped_chunks = 0
        self._sent_chunks = 0

    def _enqueue_audio(self, audio: bytes) -> None:
        if self._audio_queue.full():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._dropped_chunks += 1

        self._audio_queue.put_nowait(audio)

    def _microphone_callback(self, indata, frames, time_info, status) -> None:
        del frames, time_info

        if self._loop is None:
            return

        if status:
            self._loop.call_soon_threadsafe(
                print, f"\n[Microphone warning] {status}"
            )

        # RawInputStream already provides raw little-endian int16 PCM bytes.
        self._loop.call_soon_threadsafe(self._enqueue_audio, bytes(indata))

    def _start_microphone(self) -> None:
        sd.check_input_settings(
            device=self._input_device,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
        )

        selected = sd.query_devices(self._input_device, "input")
        print(f"Microphone: {selected['name']}")

        self._microphone = sd.RawInputStream(
            device=self._input_device,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=BLOCK_SIZE,
            latency="low",
            callback=self._microphone_callback,
        )
        self._microphone.start()

    def _stop_microphone(self) -> None:
        if self._microphone is None:
            return
        self._microphone.stop()
        self._microphone.close()
        self._microphone = None

    async def _send_microphone_audio(self, connection) -> None:
        while True:
            chunk = await self._audio_queue.get()

            if len(chunk) != BLOCK_SIZE * 2:
                print(
                    f"\n[Audio warning] expected {BLOCK_SIZE * 2} bytes, "
                    f"received {len(chunk)} bytes."
                )

            await connection.send_media(chunk)
            self._sent_chunks += 1

            if self._sent_chunks == 1:
                print(
                    f"Audio streaming started: {len(chunk)} bytes every "
                    f"{CHUNK_MS} ms."
                )

    async def _handle_message(self, message: Any) -> None:
        # deepgram-sdk versions may return either generated model objects or
        # ordinary dictionaries for Listen v2 union responses.
        message_type = _text_value(_field(message, "type"))

        if message_type == "Connected":
            request_id = _field(message, "request_id", "unknown")
            print(f"Deepgram session ready. request_id={request_id}")
            return

        if message_type in {"Error", "FatalError", "ConfigureFailure"}:
            print(f"\n[Deepgram server message] {message}")
            return

        if message_type != "TurnInfo":
            # Keep this diagnostic while integrating the service.
            print(f"\n[Deepgram message: {message_type or 'unknown'}] {message}")
            return

        event = _text_value(_field(message, "event"))
        transcript = str(_field(message, "transcript", "") or "").strip()
        raw_turn_index = _field(message, "turn_index", -1)
        turn_index = int(raw_turn_index if raw_turn_index is not None else -1)

        if event in {"Update", "StartOfTurn", "TurnResumed", "EagerEndOfTurn"}:
            if transcript and transcript != self._last_partial:
                self._last_partial = transcript
                print(f"\rPartial: {transcript:<100}", end="", flush=True)

        if event == "StartOfTurn":
            print("\n[StartOfTurn]")
            await self.events.put(
                FluxEvent(
                    kind=event,
                    transcript=transcript,
                    turn_index=turn_index,
                )
            )
            return

        if event == "TurnResumed":
            print("\n[TurnResumed] User continued speaking.")
            await self.events.put(
                FluxEvent(
                    kind=event,
                    transcript=transcript,
                    turn_index=turn_index,
                )
            )
            return

        if event == "EagerEndOfTurn":
            await self.events.put(
                FluxEvent(
                    kind=event,
                    transcript=transcript,
                    turn_index=turn_index,
                )
            )
            return

        if event != "EndOfTurn":
            return

        self._last_partial = ""
        words = tuple(_field(message, "words", ()) or ())

        confidences: list[float] = []
        low_confidence_words: list[str] = []

        for word in words:
            confidence = float(_field(word, "confidence", 0.0) or 0.0)
            confidences.append(confidence)

            if confidence < 0.75:
                token = str(
                    _field(word, "punctuated_word", None)
                    or _field(word, "word", "")
                    or ""
                )
                if token:
                    low_confidence_words.append(token)

        average_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        turn = FluxTurn(
            text=transcript,
            turn_index=turn_index,
            average_word_confidence=average_confidence,
            end_of_turn_confidence=float(
                _field(message, "end_of_turn_confidence", 0.0) or 0.0
            ),
            audio_window_start=float(
                _field(message, "audio_window_start", 0.0) or 0.0
            ),
            audio_window_end=float(
                _field(message, "audio_window_end", 0.0) or 0.0
            ),
            low_confidence_words=tuple(low_confidence_words),
        )

        print("\r" + " " * 120 + "\r", end="")
        print(f"FINAL [{turn.turn_index}]: {turn.text}")
        print(
            "Confidence: "
            f"words={turn.average_word_confidence:.2f}, "
            f"end-of-turn={turn.end_of_turn_confidence:.2f}"
        )

        if turn.low_confidence_words:
            print("Low-confidence words:", ", ".join(turn.low_confidence_words))

        if self._dropped_chunks:
            print(f"Warning: dropped microphone chunks={self._dropped_chunks}")

        if turn.text:
            await self.turns.put(turn)
            await self.events.put(
                FluxEvent(
                    kind="EndOfTurn",
                    transcript=turn.text,
                    turn_index=turn.turn_index,
                    turn=turn,
                )
            )

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()

        connect_options: dict[str, object] = {
            "model": "flux-general-en",
            "encoding": "linear16",
            "sample_rate": SAMPLE_RATE,
            "eot_threshold": self._eot_threshold,
            "eot_timeout_ms": self._eot_timeout_ms,
        }
        if self._keyterms:
            connect_options["keyterm"] = self._keyterms

        print("Connecting to Deepgram Flux...")

        async with self._client.listen.v2.connect(**connect_options) as connection: # type: ignore
            connection.on(EventType.OPEN, lambda _: print("WebSocket listener opened."))
            connection.on(EventType.MESSAGE, self._handle_message)
            connection.on(
                EventType.ERROR,
                lambda error: print(f"\n[Deepgram connection error] {error!r}"),
            )
            connection.on(
                EventType.CLOSE,
                lambda _: print("\nDeepgram connection closed."),
            )

            listener_task = asyncio.create_task(
                connection.start_listening(), name="deepgram-listener"
            )
            sender_task = asyncio.create_task(
                self._send_microphone_audio(connection), name="deepgram-audio-sender"
            )

            try:
                # Give the listener coroutine one event-loop cycle to initialize.
                await asyncio.sleep(0)
                self._start_microphone()

                print(
                    "Connected. Speak naturally; pause, think, and continue. "
                    "Press Ctrl+C to stop."
                )

                done, _ = await asyncio.wait(
                    {listener_task, sender_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    if task.cancelled():
                        continue
                    exception = task.exception()
                    if exception is not None:
                        raise RuntimeError(
                            f"{task.get_name()} stopped with an error"
                        ) from exception

                # Neither long-running task should end during a healthy session.
                ended_names = ", ".join(task.get_name() for task in done)
                raise RuntimeError(f"Streaming task ended unexpectedly: {ended_names}")

            finally:
                self._stop_microphone()

                sender_task.cancel()
                listener_task.cancel()

                try:
                    await connection.send_close_stream()
                except Exception:
                    pass

                await asyncio.gather(
                    sender_task,
                    listener_task,
                    return_exceptions=True,
                )


async def main() -> None:
    asr = DeepgramFluxASR(
        # Your current Windows device list shows Microphone Array at index 1.
        input_device=1,
        eot_threshold=0.80,
        eot_timeout_ms=7_000,
        # Keep keyterms disabled for this first connectivity test.
        # Re-enable them after final transcripts appear.
        keyterms=(),
    )
    await asr.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
