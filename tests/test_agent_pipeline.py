from __future__ import annotations

from conversation_ai.agent import pipeline
from conversation_ai.config import Settings


def test_pipeline_builders_preserve_selected_models_and_tuning(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        pipeline.deepgram,
        "STTv2",
        lambda **kwargs: captured.setdefault("stt", kwargs),
    )
    monkeypatch.setattr(
        pipeline.deepgram,
        "TTS",
        lambda **kwargs: captured.setdefault("tts", kwargs),
    )
    monkeypatch.setattr(
        pipeline.inference,
        "LLM",
        lambda **kwargs: captured.setdefault("llm", kwargs),
    )

    settings = Settings(
        _env_file=None,
        flux_eager_eot_threshold=0.61,
        flux_eot_threshold=0.82,
        flux_eot_timeout_ms=7100,
        llm_temperature=0.25,
        llm_max_completion_tokens=300,
    )
    pipeline.build_stt(settings)
    pipeline.build_llm(settings)
    pipeline.build_tts(settings)

    assert captured["stt"] == {
        "model": "flux-general-en",
        "eager_eot_threshold": 0.61,
        "eot_threshold": 0.82,
        "eot_timeout_ms": 7100,
    }
    assert captured["llm"]["model"] == "google/gemini-2.5-flash-lite"
    assert captured["llm"]["extra_kwargs"]["max_completion_tokens"] == 300
    assert captured["tts"] == {
        "model": "aura-2-andromeda-en",
        "sample_rate": 24000,
    }


def test_turn_handling_keeps_flux_barge_in_and_safe_tts_filters() -> None:
    options = pipeline.build_turn_handling_options()
    assert options["turn_detection"] == "stt"
    assert options["interruption"] == {
        "enabled": True,
        "mode": "vad",
        "min_duration": 0.4,
        "min_words": 0,
        "false_interruption_timeout": 1.5,
        "resume_false_interruption": True,
    }
    assert options["preemptive_generation"]["preemptive_tts"] is False
    assert pipeline.TTS_TEXT_TRANSFORMS == ["filter_markdown", "filter_emoji"]


def test_audio_enhancement_supports_quail_and_explicit_disable(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        pipeline.ai_coustics,
        "ModelParameters",
        lambda **kwargs: captured.setdefault("parameters", kwargs),
    )
    monkeypatch.setattr(
        pipeline.ai_coustics,
        "audio_enhancement",
        lambda **kwargs: captured.setdefault("enhancer", kwargs),
    )
    monkeypatch.setattr(
        pipeline.room_io,
        "AudioInputOptions",
        lambda **kwargs: kwargs,
    )

    enabled = pipeline.build_audio_input_options(
        Settings(_env_file=None, audio_enhancement="quail_l", audio_enhancement_level=0.75)
    )
    assert captured["parameters"] == {"enhancement_level": 0.75}
    assert enabled["noise_cancellation"] == captured["enhancer"]

    disabled = pipeline.build_audio_input_options(
        Settings(_env_file=None, audio_enhancement="none")
    )
    assert disabled == {}
