from __future__ import annotations

import unittest

from app.realtime.guided_conversation import (
    GuidedRuntimeController,
    _recognition_feedback,
)


class GuidedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_word_color_thresholds_are_exact(self) -> None:
        words = [
            {"word": "red", "confidence": 0.24},
            {"word": "orange-low", "confidence": 0.25},
            {"word": "orange-high", "confidence": 0.74},
            {"word": "white", "confidence": 0.75},
        ]
        feedback = _recognition_feedback("", words)
        self.assertEqual(
            ["red", "orange", "orange", "white"],
            [item["color_band"] for item in feedback],
        )

    async def test_completed_session_never_speaks_inactive_warning(self) -> None:
        controller = GuidedRuntimeController(
            room=object(),
            session_id="guided-complete",
            client=object(),  # type: ignore[arg-type]
            recorder=object(),  # type: ignore[arg-type]
        )
        controller.view = {"status": "completed", "state": "completed"}
        await controller.handle_user_turn("I")
        self.assertEqual("", controller.consume_spoken_reply())


if __name__ == "__main__":
    unittest.main()
