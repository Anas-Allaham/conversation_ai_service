from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from conversation_ai.config import get_settings


def main() -> int:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value().strip()
    if not database_url:
        print("ERROR: DATABASE_URL is missing from .env.local.")
        return 1

    parsed = urlsplit(database_url)
    if parsed.scheme.startswith("sqlite"):
        database_path = database_url.split("///", 1)[-1]
        if database_path and database_path != ":memory:":
            path = Path(database_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
        print("Configuration preflight: local SQLite database selected.")
        return 0

    if parsed.scheme in {"postgres", "postgresql", "postgresql+asyncpg"}:
        placeholder_values = {"host", "db.example.com", "user", "password"}
        if (
            not parsed.hostname
            or parsed.hostname.lower() in placeholder_values
            or (parsed.username or "").lower() in placeholder_values
            or (parsed.password or "").lower() in placeholder_values
        ):
            print(
                "ERROR: DATABASE_URL still contains example PostgreSQL values. "
                "Use a real reachable PostgreSQL URL, or use the local SQLite "
                "value from .env.example."
            )
            return 1
        print(f"Configuration preflight: PostgreSQL host {parsed.hostname!r} selected.")
        return 0

    print("ERROR: DATABASE_URL must use sqlite or postgresql.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
