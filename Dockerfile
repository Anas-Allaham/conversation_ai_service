# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra agent --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra agent

# Download Silero/plugin assets into the immutable image, not at runtime.
RUN uv run --no-sync python -m livekit.agents download-files

FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos "" --home /app --uid 10001 appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app
USER appuser

EXPOSE 8081
CMD ["python", "src/agent.py", "start"]
