from livekit import agents

from conversation_ai.agent.worker import server

if __name__ == "__main__":
    agents.cli.run_app(server)
