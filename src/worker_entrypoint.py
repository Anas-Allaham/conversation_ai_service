from __future__ import annotations

import os

from livekit import agents


def selected_server():
    role = os.getenv("WORKER_ROLE", "tutor").strip().lower()
    if role == "tutor":
        from conversation_ai.agent.worker import server

        return server
    if role == "assessment":
        from app.realtime.assessment_agent import server

        return server
    raise RuntimeError("WORKER_ROLE must be 'tutor' or 'assessment'")


if __name__ == "__main__":
    agents.cli.run_app(selected_server())
