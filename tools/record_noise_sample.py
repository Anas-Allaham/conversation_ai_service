from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

DEFAULT_TEXT = (
    "I am studying information technology at Damascus University. "
    "I am in my final year, and my specialization is artificial intelligence. "
    "Can you tell me what slang means?"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record one untouched microphone sample for fair noise-filter "
            "A/B testing. The same WAV file should be passed through every "
            "candidate filter."
        )
    )
    parser.add_argument(
        "--device",
        default=None,
        help=(
            "Input-device index or exact/partial device name. "
            "Run `python -m sounddevice` to list devices."
        ),
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=20.0,
        help="Recording duration in seconds. Default: 20.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("samples/noisy_reference.wav"),
        help="Output WAV path.",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Reference sentence shown before recording.",
    )
    return parser.parse_args()


def resolve_device(device_arg: str | None) -> int | str | None:
    if device_arg is None:
        return None

    try:
        return int(device_arg)
    except ValueError:
        return device_arg


def main() -> None:
    args = parse_args()
    device = resolve_device(args.device)

    info = sd.query_devices(device, "input")
    sample_rate = int(round(float(info["default_samplerate"])))
    channels = 1
    frames = int(args.seconds * sample_rate)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    transcript_path = args.output.with_suffix(".txt")
    metadata_path = args.output.with_suffix(".json")

    transcript_path.write_text(args.text.strip() + "\n", encoding="utf-8")

    print("\nRead this exact text while background talk is present:\n")
    print(args.text)
    print(f"\nInput device: {info['name']}")
    print(f"Sample rate: {sample_rate} Hz")
    print(f"Duration: {args.seconds:.1f} seconds")
    print("\nRecording begins in:")

    for remaining in (3, 2, 1):
        print(remaining, flush=True)
        time.sleep(1)

    print("RECORDING...")

    audio = sd.rec(
        frames,
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        device=device,
    )
    sd.wait()

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0

    # PCM_16 is portable and accepted by common speech tools.
    sf.write(
        args.output,
        audio,
        sample_rate,
        subtype="PCM_16",
    )

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "device": str(info["name"]),
        "device_argument": args.device,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "duration_seconds": args.seconds,
        "peak": peak,
        "rms": rms,
        "reference_transcript_file": str(transcript_path),
        "audio_file": str(args.output),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:")
    print(f"  Audio:      {args.output}")
    print(f"  Transcript: {transcript_path}")
    print(f"  Metadata:   {metadata_path}")
    print(f"  RMS:        {rms:.6f}")
    print(f"  Peak:       {peak:.6f}")

    if peak >= 0.99:
        print(
            "\nWarning: clipping detected. Lower microphone gain or move "
            "slightly farther from the microphone and record again."
        )
    elif peak < 0.05:
        print(
            "\nWarning: the recording is very quiet. Move closer to the "
            "microphone or raise input gain and record again."
        )


if __name__ == "__main__":
    main()
