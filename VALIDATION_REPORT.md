# Integration validation report

Validated on 2026-08-15 with Python 3.12.

## Passed checks

- `uv lock` and `uv sync --all-extras`
- Python bytecode compilation for `src` and Alembic migrations
- Ruff static checks
- 108 automated tests
- Versioned item-bank validator: 16 records, expected A1-B2 distribution
- Guided catalog validator: Restaurant and Airport, four deterministic scenarios
- Wheel build and package-data inspection
- Shared-app contract test covering existing `/api/v1`, integrated `/v1`, auth,
  health, Free/Guided domain discovery, and secure assessment-session creation
- Worker metadata tests for both the original team schema and the new practice schema
- Persistence test proving guided assistant/learner turns are queryable through
  the team conversation repository
- Full Alembic upgrade from an empty SQLite database through revision
  `0003_tutor_modules`
- Setup preflight acceptance of SQLite and rejection of the example PostgreSQL URL

## Runtime checks requiring deployment credentials

Live WebRTC audio, provider calls, and LiveKit Cloud dispatch cannot be exercised
without the deployment's LiveKit, Deepgram, evaluator, and production PostgreSQL
credentials.
Run `scripts/setup.ps1`, then the API/tutor/assessor scripts, and complete one
Free, one Guided, and one assessment smoke session in the target environment.

The Piper model is intentionally not committed to the project archive. The setup
script downloads it once; Docker/Modal builds download the same pinned voice into
their images.
