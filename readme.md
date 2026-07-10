# Realtime English Tutor

A lightweight realtime speech-based English tutor that records user speech, transcribes it, uses an LLM to generate responses, converts responses to speech, and plays them back in a loop.

## Main Flow

1. User speaks
2. Record until silence
3. Save WAV
4. Whisper transcribe
5. LLM processes/transforms text (feedback, correction, or reply)
6. Generate entire TTS file (single audio output for the reply)
7. Play file
8. Wait
9. Repeat

## Features

- Voice activity detection (record until silence)
- Local WAV saving for debugging and logging
- Whisper (or equivalent) for reliable speech-to-text
- LLM-based response generation for tutoring, corrections, and dialogue
- Text-to-speech output to produce natural-sounding replies
- Simple loop designed for realtime back-and-forth practice

## Architecture Overview

- Input: microphone audio captured and VAD-backed to determine end of utterance
- Persistence: save captured audio as WAV
- STT: Whisper (or cloud alternative) transcribes WAV -> text
- LLM: receives transcript + conversation/context and returns tutor reply (and corrections)
- TTS: renders the LLM reply into a single WAV/MP3 file
- Output: play the rendered audio and wait for next user utterance

## Installation (example)

1. Create a virtual environment and activate it:

   python -m venv venv
   venv\Scripts\activate (Windows)

2. Install dependencies (example packages):

   pip install -r requirements.txt

3. Configure API keys and models in environment variables or a config file (Whisper, LLM, TTS provider).

## Usage

- Run the main application (replace with your entrypoint):
  python main.py
- Speak when prompted. The app will record until silence, transcribe, generate a reply, synthesize speech, and play it back.

## Tips

- Tune VAD/silence thresholds for reliable end-of-utterance detection.
- Cache recent conversation context to keep LLM responses coherent.
- Use short TTS segments only if you need partial/streaming playback; the default is a single-file reply.

## Troubleshooting

- No audio recorded: check microphone permissions and device selection.
- Poor transcription: try a higher-quality Whisper model or noise reduction preprocessing.
- LLM hallucinations: provide system prompts and few-shot examples to constrain output.

## License

Specify your project license here.

## Contributing

Open issues or pull requests with focused, small changes. Include reproducible steps for bugs.

## Contact

Aya Sareej aya.sareej.it@gmail.com
