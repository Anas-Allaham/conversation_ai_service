from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from typing import Any

from livekit.agents import Agent, TurnHandlingOptions, inference, room_io
from livekit.plugins import ai_coustics, deepgram, silero

from ..config import Settings

logger = logging.getLogger("conversation-ai.pipeline")
TTS_TEXT_TRANSFORMS = ["filter_markdown", "filter_emoji"]

TUTOR_INSTRUCTIONS = """
You are a friendly English tutor in a live spoken conversation.

Conversation behavior:
- Listen carefully and answer what the learner actually asks.
- Maintain context across turns.
- Use natural spoken English.
- Keep greetings and casual replies brief, usually one or two sentences.
- For grammar, vocabulary, or deeper questions, explain the central idea clearly first.
- Give explanations in conversational chunks. Ask whether the learner wants an
  example or more detail instead of giving a long lecture by default.
- Give a long answer only when the learner explicitly asks for detail.
- Do not begin every answer with filler praise. Start with the useful answer.
- If the transcript is semantically strange and may contain an ASR error, ask
  one brief clarification question instead of inventing a confident meaning.
- When the learner corrects a misunderstood word, acknowledge the correction
  briefly and continue with the corrected meaning.
- Allow the learner to interrupt, correct the topic, or change direction.
- Correct grammar gently and only when useful. Do not correct every sentence.
- Never use ASR confidence as a pronunciation score.

Speech-output rules:
- Produce plain spoken text only.
- Do not use Markdown, asterisks, headings, bullet symbols, emojis, code fences,
  URLs, or decorative formatting.
- Write numbers and abbreviations in forms that sound natural when spoken.
""".strip()


class EnglishTutor(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=TUTOR_INSTRUCTIONS)


class FluencyTrackingTutor(EnglishTutor):
    """Keep the original tutor behavior while capturing Flux word timings."""

    def __init__(self, tracker) -> None:
        super().__init__()
        self.tracker = tracker

    async def stt_node(self, audio, model_settings) -> AsyncIterable[Any]:
        async for event in Agent.default.stt_node(self, audio, model_settings):
            self.tracker.observe_stt_event(event)
            yield event


def build_stt(settings: Settings) -> deepgram.STTv2:
    return deepgram.STTv2(
        model="flux-general-en",
        eager_eot_threshold=settings.flux_eager_eot_threshold,
        eot_threshold=settings.flux_eot_threshold,
        eot_timeout_ms=settings.flux_eot_timeout_ms,
    )


def build_vad():
    return silero.VAD.load(
        min_speech_duration=0.08,
        min_silence_duration=0.55,
        prefix_padding_duration=0.50,
        activation_threshold=0.50,
    )


def build_llm(settings: Settings) -> inference.LLM:
    logger.info("llm_configured", extra={"model": settings.livekit_llm_model})
    return inference.LLM(
        model=settings.livekit_llm_model,
        extra_kwargs={
            "temperature": settings.llm_temperature,
            "max_completion_tokens": settings.llm_max_completion_tokens,
        },
    )


def build_tts(settings: Settings) -> deepgram.TTS:
    logger.info("tts_configured", extra={"model": settings.deepgram_tts_model})
    return deepgram.TTS(model=settings.deepgram_tts_model, sample_rate=24_000)


def build_turn_handling_options() -> TurnHandlingOptions:
    return TurnHandlingOptions(
        turn_detection="stt",
        endpointing={"mode": "fixed", "min_delay": 0.0, "max_delay": 1.0},
        interruption={
            "enabled": True,
            "mode": "vad",
            "min_duration": 0.40,
            "min_words": 0,
            "false_interruption_timeout": 1.50,
            "resume_false_interruption": True,
        },
        preemptive_generation={
            "enabled": True,
            "preemptive_tts": False,
            "max_speech_duration": 12.0,
            "max_retries": 1,
        },
    )


def build_audio_input_options(settings: Settings) -> room_io.AudioInputOptions:
    if settings.audio_enhancement == "none":
        logger.info("audio_enhancement_disabled")
        return room_io.AudioInputOptions()

    kwargs: dict[str, object] = {"model": ai_coustics.EnhancerModel.QUAIL_L}
    if settings.audio_enhancement_level is not None:
        kwargs["model_parameters"] = ai_coustics.ModelParameters(
            enhancement_level=settings.audio_enhancement_level
        )

    enhancer = ai_coustics.audio_enhancement(**kwargs)
    logger.info(
        "audio_enhancement_enabled",
        extra={"model": "quail_l", "level": settings.audio_enhancement_level},
    )
    return room_io.AudioInputOptions(noise_cancellation=enhancer)
