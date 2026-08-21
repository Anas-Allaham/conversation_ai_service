from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import modal

APP_NAME = "conversation-ai-service"
APP_DIR = "/root/conversation-ai-service"
PROJECT_DIR = Path(__file__).resolve().parent

runtime_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_pyproject(
        str(PROJECT_DIR / "pyproject.toml"),
        optional_dependencies=["api"],
    )
    .run_commands(
        f"mkdir -p {APP_DIR}/data/piper",
        "python -m piper.download_voices "
        f"--data-dir {APP_DIR}/data/piper en_US-lessac-medium",
    )
    .add_local_dir(str(PROJECT_DIR / "src"), remote_path=f"{APP_DIR}/src", copy=True)
    .add_local_dir(
        str(PROJECT_DIR / "migrations"),
        remote_path=f"{APP_DIR}/migrations",
        copy=True,
    )
    .add_local_file(
        str(PROJECT_DIR / "alembic.ini"),
        remote_path=f"{APP_DIR}/alembic.ini",
        copy=True,
    )
)

app = modal.App(APP_NAME)
runtime_secrets = [modal.Secret.from_name("conversation-ai-service-secrets")]


def configure_runtime() -> None:
    os.chdir(APP_DIR)
    source_dir = f"{APP_DIR}/src"
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)


@app.function(image=runtime_image, secrets=runtime_secrets, timeout=300)
def migrate() -> None:
    """Apply PostgreSQL migrations before deploying either process."""
    configure_runtime()
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@app.function(
    image=runtime_image,
    secrets=runtime_secrets,
    timeout=300,
    scaledown_window=600,
    max_containers=10,
)
@modal.asgi_app()
def web():
    configure_runtime()
    from conversation_ai.api.main import app as fastapi_app

    return fastapi_app
