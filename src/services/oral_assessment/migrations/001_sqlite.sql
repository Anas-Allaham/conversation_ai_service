PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assessments (
    assessment_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    assessment_id TEXT NOT NULL,
    response_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    prompt_kind TEXT NOT NULL,
    stored_response_json TEXT NOT NULL,
    api_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (assessment_id, response_id),
    UNIQUE (assessment_id, idempotency_key),
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_responses_assessment_prompt
ON responses(assessment_id, prompt_kind, item_id);

CREATE TABLE IF NOT EXISTS pronunciation_diagnostics (
    assessment_id TEXT PRIMARY KEY,
    diagnostic_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id TEXT PRIMARY KEY,
    assessment_id TEXT,
    correlation_id TEXT,
    event_type TEXT NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_assessment_created
ON audit_logs(assessment_id, created_at);

CREATE TABLE IF NOT EXISTS runtime_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

