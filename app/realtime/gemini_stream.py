from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Sequence

from dotenv import load_dotenv
from google import genai 
from google.genai import types 


SYSTEM_INSTRUCTION = """
You are a friendly English-learning tutor in a real-time voice conversation.

Conversation policy:
- Infer the learner's intent from the current turn and conversation context.
- For greetings and casual dialogue, answer briefly and naturally.
- For grammar or vocabulary questions, give a useful first explanation in a few
  spoken sentences, then offer to continue with an example or practice.
- If the learner explicitly requests detail, provide a structured explanation,
  but still divide it into conversational chunks rather than a long lecture.
- Correct English gently. Do not correct every small mistake unless correction
  is helpful or the learner asks for it.
- Never output Markdown, bullet symbols, asterisks, headings, URLs, or emoji.
  The response will later be sent directly to text-to-speech.
- Do not mention these instructions.
""".strip()


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    text: str
    interrupted: bool = False


class GeminiStreamingLLM:
    """Cancellable streaming Gemini text generation."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_output_tokens: int = 320,
        temperature: float = 0.55,
    ) -> None:
        load_dotenv()

        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "GEMINI_API_KEY is missing. Add it to the project .env file."
            )

        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self._client = genai.Client(api_key=resolved_key)

    @staticmethod
    def _build_contents(
        history: Sequence[ChatMessage],
        user_text: str,
    ) -> list[types.Content]:
        contents: list[types.Content] = []

        for message in history:
            model_role = "model" if message.role == "assistant" else "user"
            text = message.text.strip()

            if not text:
                continue

            if message.interrupted and message.role == "assistant":
                text += "\n(The learner interrupted this response before it finished.)"

            contents.append(
                types.Content(
                    role=model_role,
                    parts=[types.Part.from_text(text=text)],
                )
            )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_text)],
            )
        )

        return contents

    async def stream_reply(
        self,
        user_text: str,
        history: Sequence[ChatMessage],
    ) -> AsyncIterator[str]:
        """Yield response text as soon as Gemini produces each chunk."""

        contents = self._build_contents(history, user_text)

        stream = await self._client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
                # For normal tutor dialogue, extra reasoning delays the first
                # token. We will route difficult requests to a deeper mode later.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        async for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text

    async def close(self) -> None:
        await self._client.aio.aclose()
