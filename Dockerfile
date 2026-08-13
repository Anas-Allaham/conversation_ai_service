FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY app ./app
COPY services ./services
RUN pip install --no-cache-dir ".[livekit]"

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/audio \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
CMD ["uvicorn", "services.oral_assessment.main:app", "--host", "0.0.0.0", "--port", "8080"]
