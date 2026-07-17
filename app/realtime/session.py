from __future__ import annotations

import asyncio
import contextlib
import os
import time

from app.realtime.flux_asr import DeepgramFluxASR, FluxEvent, FluxTurn
from app.realtime.gemini_stream import ChatMessage, GeminiStreamingLLM


class RealtimeTutorSession:
    """Coordinates Flux events and cancellable Gemini generation.

    This phase intentionally outputs text only. Audio output is added only after
    the transport has echo cancellation; otherwise the always-open microphone
    would transcribe the assistant's own speaker audio.
    """

    def __init__(self) -> None:
        self.asr = DeepgramFluxASR(
            input_device=self._read_input_device(),
            eot_threshold=0.80,
            eot_timeout_ms=7_000,
            keyterms=(
                "conversation skills",
                "pronunciation",
                "vocabulary",
                "past perfect",
                "present perfect",
                "phoneme",
            ),
        )
        self.llm = GeminiStreamingLLM()

        self.history: list[ChatMessage] = []
        self._response_task: asyncio.Task[None] | None = None

    @staticmethod
    def _read_input_device() -> int | str | None:
        raw = os.getenv("AUDIO_INPUT_DEVICE", "1").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return raw

    async def run(self) -> None:
        asr_task = asyncio.create_task(
            self.asr.run(),
            name="flux-asr",
        )
        event_task = asyncio.create_task(
            self._consume_flux_events(),
            name="conversation-controller",
        )

        print("\n=== Realtime English Tutor: ASR + streaming LLM ===\n")

        try:
            done, _ = await asyncio.wait(
                {asr_task, event_task},
                return_when=asyncio.FIRST_EXCEPTION,
            )

            for task in done:
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error

        finally:
            await self._cancel_response("session shutting down")

            asr_task.cancel()
            event_task.cancel()

            await asyncio.gather(
                asr_task,
                event_task,
                return_exceptions=True,
            )

            await self.llm.close()

    async def _consume_flux_events(self) -> None:
        while True:
            event = await self.asr.events.get()
            await self._handle_flux_event(event)

    async def _handle_flux_event(self, event: FluxEvent) -> None:
        if event.kind == "StartOfTurn":
            # This is the logical foundation of barge-in. When audio playback is
            # added, the same method will also cancel TTS and speaker playout.
            await self._cancel_response("learner started speaking")
            return

        if event.kind == "TurnResumed":
            await self._cancel_response("learner resumed the same turn")
            return

        if event.kind == "EagerEndOfTurn":
            # Speculative generation is deliberately disabled in this phase.
            return

        if event.kind != "EndOfTurn" or event.turn is None:
            return

        await self._cancel_response("a newer final turn arrived")

        self._response_task = asyncio.create_task(
            self._respond_to_turn(event.turn),
            name=f"llm-response-turn-{event.turn.turn_index}",
        )

    async def _respond_to_turn(self, turn: FluxTurn) -> None:
        user_text = turn.text.strip()
        if not user_text:
            return

        print(f"\nYou: {user_text}")
        print(
            "ASR: "
            f"word confidence={turn.average_word_confidence:.2f}, "
            f"end-of-turn confidence={turn.end_of_turn_confidence:.2f}"
        )

        if turn.low_confidence_words:
            print(
                "ASR low-confidence words: "
                + ", ".join(turn.low_confidence_words)
            )

        # Store the user's committed turn immediately. If the assistant is
        # interrupted, the user's message must remain in conversation context.
        self.history.append(
            ChatMessage(role="user", text=user_text)
        )

        generated_chunks: list[str] = []
        started_at = time.perf_counter()
        first_chunk_at: float | None = None

        print("AI: ", end="", flush=True)

        try:
            async for chunk in self.llm.stream_reply(
                user_text=user_text,
                # Exclude the user message just appended, because stream_reply
                # adds the current user turn itself.
                history=self.history[:-1],
            ):
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()

                generated_chunks.append(chunk)
                print(chunk, end="", flush=True)

        except asyncio.CancelledError:
            partial = "".join(generated_chunks).strip()

            if partial:
                self.history.append(
                    ChatMessage(
                        role="assistant",
                        text=partial,
                        interrupted=True,
                    )
                )

            print("\n[Assistant response cancelled]")
            raise

        except Exception as error:
            print(f"\n[Gemini error] {error!r}")
            return

        answer = "".join(generated_chunks).strip()
        finished_at = time.perf_counter()

        if answer:
            self.history.append(
                ChatMessage(role="assistant", text=answer)
            )

        print()

        if first_chunk_at is not None:
            first_token_ms = (first_chunk_at - started_at) * 1_000
            total_ms = (finished_at - started_at) * 1_000
            print(
                f"[LLM latency: first text={first_token_ms:.0f} ms, "
                f"complete={total_ms:.0f} ms]"
            )

    async def _cancel_response(self, reason: str) -> None:
        task = self._response_task

        if task is None or task.done():
            return

        print(f"\n[Cancelling assistant: {reason}]")
        task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await task

        self._response_task = None


async def main() -> None:
    session = RealtimeTutorSession()
    await session.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
