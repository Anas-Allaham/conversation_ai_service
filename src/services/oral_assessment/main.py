from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from .integration import install_tutor_modules


def create_app(project_root: Path | None = None) -> FastAPI:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    load_dotenv(root / ".env.local")
    load_dotenv(root / ".env", override=False)

    app = FastAPI(
        title="English Tutor Assessment and Practice Service",
        version="0.7.0",
        description=(
            "CEFR-aligned adaptive oral placement plus deterministic guided role-play "
            "practice. Guided practice does not issue or change CEFR placement."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )
    settings = install_tutor_modules(
        app,
        project_root=root,
        expose_settings_as_primary=True,
    )
    app.version = settings.assessment_version
    app.state.initialize_tutor_modules()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return app
