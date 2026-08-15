from pathlib import Path

from dotenv import load_dotenv
from livekit import agents

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env", override=False)


if __name__ == "__main__":
    from app.realtime.assessment_agent import server

    agents.cli.run_app(server)
