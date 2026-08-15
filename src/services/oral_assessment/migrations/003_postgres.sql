CREATE TABLE IF NOT EXISTS guided_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_guided_sessions_user_updated
ON guided_sessions(user_id, updated_at);

CREATE TABLE IF NOT EXISTS guided_attempt_replays (
    session_id TEXT NOT NULL REFERENCES guided_sessions(session_id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    api_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, attempt_id),
    UNIQUE (session_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS guided_audio_assets (
    session_id TEXT NOT NULL REFERENCES guided_sessions(session_id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL,
    audio_uri TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, attempt_id)
);
