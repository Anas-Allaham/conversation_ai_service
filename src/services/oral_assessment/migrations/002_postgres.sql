CREATE TABLE IF NOT EXISTS fluency_observations (
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_id)
);

CREATE INDEX IF NOT EXISTS idx_fluency_observations_session_created
ON fluency_observations(session_id, created_at);
