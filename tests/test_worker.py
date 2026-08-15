from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from conversation_ai.agent.worker import PERSISTENCE_KEY, on_session_end


async def test_session_end_without_agent_session_skips_livekit_report() -> None:
    persistence = SimpleNamespace(
        metadata=SimpleNamespace(session_id=uuid.uuid4()),
        flush=AsyncMock(),
        close=AsyncMock(),
    )
    context = SimpleNamespace(
        proc=SimpleNamespace(userdata={PERSISTENCE_KEY: persistence}),
        make_session_report=Mock(side_effect=AssertionError("report must not be built")),
    )

    await on_session_end(context)

    persistence.flush.assert_awaited_once()
    persistence.close.assert_awaited_once()
    context.make_session_report.assert_not_called()

