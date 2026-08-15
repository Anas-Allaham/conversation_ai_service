from __future__ import annotations

import asyncio
import io
import logging
import wave

from .assessment_client import AssessmentClient

logger = logging.getLogger(__name__)


class RawAudioSegmentRecorder:
    """Records the original remote microphone track before AgentSession enhancement."""

    def __init__(self, client: AssessmentClient, sample_rate: int = 48_000, channels: int = 1) -> None:
        self.client = client
        self.sample_rate = sample_rate
        self.channels = channels
        self._buffer = bytearray()
        self._active = False
        self._stream_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def attach_track(self, track) -> None:
        if self._stream_task and not self._stream_task.done():
            return
        self._stream_task = asyncio.create_task(self._consume(track))

    async def _consume(self, track) -> None:
        try:
            from livekit import rtc

            stream = rtc.AudioStream(track, sample_rate=self.sample_rate, num_channels=self.channels)
            async for event in stream:
                frame = getattr(event, "frame", event)
                if self._active:
                    async with self._lock:
                        self._buffer.extend(bytes(frame.data))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Raw microphone capture stopped")

    async def start_segment(self, *, reset: bool = True) -> None:
        async with self._lock:
            if reset:
                self._buffer.clear()
            self._active = True

    async def pause_segment(self, *, preserve: bool = True) -> None:
        """Pause capture between committed fragments of one learner response."""
        async with self._lock:
            self._active = False
            if not preserve:
                self._buffer.clear()

    async def stop_and_upload(
        self,
        assessment_id: str,
        response_id: str,
        *,
        upload: bool = True,
    ) -> str | None:
        async with self._lock:
            self._active = False
            pcm = bytes(self._buffer)
            self._buffer.clear()
        if not pcm or not upload:
            return None
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)
        try:
            return await self.client.upload_audio_async(assessment_id, response_id, output.getvalue())
        except Exception:
            logger.exception("Could not upload original microphone segment")
            return None

    async def stop_and_upload_guided(
        self,
        session_id: str,
        attempt_id: str,
        *,
        upload: bool = True,
    ) -> str | None:
        async with self._lock:
            self._active = False
            pcm = bytes(self._buffer)
            self._buffer.clear()
        if not pcm or not upload:
            return None
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)
        try:
            return await self.client.upload_guided_audio_async(
                session_id,
                attempt_id,
                output.getvalue(),
            )
        except Exception:
            logger.exception("Could not upload original guided-practice segment")
            return None

    async def close(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
