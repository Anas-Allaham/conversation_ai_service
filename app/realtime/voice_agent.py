"""Compatibility entrypoint for the canonical merged English tutor worker."""

from livekit import agents

from conversation_ai.agent.worker import english_tutor_session, server

__all__ = ["english_tutor_session", "server"]


if __name__ == "__main__":
    agents.cli.run_app(server)
