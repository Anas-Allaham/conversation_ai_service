from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from services.fluency.models import FluencyObservationResult

from .models import (
    AssessmentRecord,
    PronunciationDiagnostic,
    ResponseResult,
    StoredResponse,
    utc_now,
)


class RepositoryError(RuntimeError):
    pass


class ConcurrencyConflict(RepositoryError):
    pass


class AssessmentRepository(Protocol):
    def initialize(self) -> None: ...
    def create_assessment(self, record: AssessmentRecord, correlation_id: str = "") -> None: ...
    def get_assessment(self, assessment_id: str) -> AssessmentRecord | None: ...
    def save_record(self, record: AssessmentRecord) -> None: ...
    def save_transition(
        self,
        record: AssessmentRecord,
        stored_response: StoredResponse,
        api_result: ResponseResult,
        correlation_id: str = "",
    ) -> None: ...
    def get_response_replay(self, assessment_id: str, idempotency_key: str) -> ResponseResult | None: ...
    def get_response_by_id(self, assessment_id: str, response_id: str) -> ResponseResult | None: ...
    def list_responses(self, assessment_id: str) -> list[StoredResponse]: ...
    def save_pronunciation(self, assessment_id: str, diagnostic: PronunciationDiagnostic) -> None: ...
    def get_pronunciation(self, assessment_id: str) -> PronunciationDiagnostic | None: ...
    def audit(self, event_type: str, payload: dict[str, Any], assessment_id: str | None = None, correlation_id: str = "") -> None: ...
    def set_runtime_setting(self, key: str, value: str) -> None: ...
    def get_runtime_setting(self, key: str) -> str | None: ...
    def save_fluency_observation(self, result: FluencyObservationResult) -> FluencyObservationResult: ...
    def get_fluency_observation(self, session_id: str, turn_id: str) -> FluencyObservationResult | None: ...
    def list_fluency_observations(self, session_id: str) -> list[FluencyObservationResult]: ...


MIGRATIONS_ROOT = Path(__file__).with_name("migrations")


class SQLRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._is_sqlite = database_url.startswith("sqlite:///")
        self._lock = threading.RLock()
        if self._is_sqlite:
            raw_path = database_url.removeprefix("sqlite:///")
            self._sqlite_path = Path(raw_path).resolve()
        elif database_url.startswith(("postgresql://", "postgres://")):
            self._sqlite_path = None
        else:
            raise RepositoryError("ASSESSMENT_DATABASE_URL must use sqlite:/// or postgresql://")

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self._is_sqlite:
            assert self._sqlite_path is not None
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._sqlite_path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        else:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RepositoryError("Install psycopg[binary] for PostgreSQL") from exc
            connection = psycopg.connect(self.database_url, row_factory=dict_row)
        try:
            yield connection
        finally:
            connection.close()

    def _query(self, sql: str) -> str:
        return sql if self._is_sqlite else sql.replace("?", "%s")

    def initialize(self) -> None:
        backend = "sqlite" if self._is_sqlite else "postgres"
        migrations = sorted(MIGRATIONS_ROOT.glob(f"*_{backend}.sql"))
        if not migrations:
            raise RepositoryError(f"No {backend} migrations were found")
        with self._lock, self._connection() as connection:
            for migration in migrations:
                schema = migration.read_text(encoding="utf-8")
                if self._is_sqlite:
                    connection.executescript(schema)
                else:
                    with connection:
                        for statement in (part.strip() for part in schema.split(";")):
                            if statement:
                                connection.execute(statement)

    def create_assessment(self, record: AssessmentRecord, correlation_id: str = "") -> None:
        now = record.created_at.isoformat()
        with self._lock, self._connection() as connection, connection:
            connection.execute(
                self._query(
                    "INSERT INTO assessments(assessment_id,user_id,status,record_json,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?)"
                ),
                (
                    record.assessment_id,
                    record.user_id,
                    record.status.value,
                    record.model_dump_json(),
                    record.revision,
                    now,
                    record.updated_at.isoformat(),
                ),
            )
        self.audit(
            "assessment.created",
            {"status": record.status.value, "versions": record.versions.model_dump()},
            record.assessment_id,
            correlation_id,
        )

    def get_assessment(self, assessment_id: str) -> AssessmentRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                self._query("SELECT record_json,revision FROM assessments WHERE assessment_id=?"),
                (assessment_id,),
            ).fetchone()
        if row is None:
            return None
        record = AssessmentRecord.model_validate_json(row["record_json"])
        return record.model_copy(update={"revision": int(row["revision"])})

    def save_record(self, record: AssessmentRecord) -> None:
        expected_revision = record.revision
        updated_record = record.model_copy(update={"revision": expected_revision + 1})
        with self._lock, self._connection() as connection, connection:
            cursor = connection.execute(
                self._query(
                    "UPDATE assessments SET status=?,record_json=?,revision=?,updated_at=? WHERE assessment_id=? AND revision=?"
                ),
                (
                    updated_record.status.value,
                    updated_record.model_dump_json(),
                    updated_record.revision,
                    updated_record.updated_at.isoformat(),
                    updated_record.assessment_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyConflict(f"Assessment {record.assessment_id} changed concurrently")
        record.revision = updated_record.revision

    def save_transition(
        self,
        record: AssessmentRecord,
        stored_response: StoredResponse,
        api_result: ResponseResult,
        correlation_id: str = "",
    ) -> None:
        expected_revision = record.revision
        updated_record = record.model_copy(update={"revision": expected_revision + 1})
        with self._lock, self._connection() as connection, connection:
            replay = connection.execute(
                self._query(
                    "SELECT api_result_json FROM responses WHERE assessment_id=? AND idempotency_key=?"
                ),
                (record.assessment_id, stored_response.submission.idempotency_key),
            ).fetchone()
            if replay is not None:
                return
            cursor = connection.execute(
                self._query(
                    "UPDATE assessments SET status=?,record_json=?,revision=?,updated_at=? WHERE assessment_id=? AND revision=?"
                ),
                (
                    updated_record.status.value,
                    updated_record.model_dump_json(),
                    updated_record.revision,
                    updated_record.updated_at.isoformat(),
                    updated_record.assessment_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyConflict(f"Assessment {record.assessment_id} changed concurrently")
            connection.execute(
                self._query(
                    "INSERT INTO responses(assessment_id,response_id,idempotency_key,prompt_id,item_id,prompt_kind,stored_response_json,api_result_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)"
                ),
                (
                    record.assessment_id,
                    stored_response.submission.response_id,
                    stored_response.submission.idempotency_key,
                    stored_response.submission.prompt_id,
                    stored_response.submission.item_id,
                    stored_response.submission.prompt_kind.value,
                    stored_response.model_dump_json(),
                    api_result.model_dump_json(),
                    stored_response.created_at.isoformat(),
                ),
            )
        record.revision = updated_record.revision
        self.audit(
            "response.scored",
            {
                "response_id": stored_response.submission.response_id,
                "prompt_kind": stored_response.submission.prompt_kind.value,
                "decision": api_result.response_decision.value,
                "next_action": api_result.next_action.type.value,
            },
            record.assessment_id,
            correlation_id,
        )

    def get_response_replay(self, assessment_id: str, idempotency_key: str) -> ResponseResult | None:
        with self._connection() as connection:
            row = connection.execute(
                self._query(
                    "SELECT api_result_json FROM responses WHERE assessment_id=? AND idempotency_key=?"
                ),
                (assessment_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        result = ResponseResult.model_validate_json(row["api_result_json"])
        return result.model_copy(update={"idempotent_replay": True})

    def get_response_by_id(self, assessment_id: str, response_id: str) -> ResponseResult | None:
        with self._connection() as connection:
            row = connection.execute(
                self._query(
                    "SELECT api_result_json FROM responses WHERE assessment_id=? AND response_id=?"
                ),
                (assessment_id, response_id),
            ).fetchone()
        return None if row is None else ResponseResult.model_validate_json(row["api_result_json"])

    def list_responses(self, assessment_id: str) -> list[StoredResponse]:
        with self._connection() as connection:
            rows = connection.execute(
                self._query(
                    "SELECT stored_response_json FROM responses WHERE assessment_id=? ORDER BY created_at,response_id"
                ),
                (assessment_id,),
            ).fetchall()
        return [StoredResponse.model_validate_json(row["stored_response_json"]) for row in rows]

    def save_pronunciation(self, assessment_id: str, diagnostic: PronunciationDiagnostic) -> None:
        now = utc_now().isoformat()
        with self._lock, self._connection() as connection, connection:
            connection.execute(
                self._query(
                    "INSERT INTO pronunciation_diagnostics(assessment_id,diagnostic_json,updated_at) VALUES(?,?,?) ON CONFLICT(assessment_id) DO UPDATE SET diagnostic_json=excluded.diagnostic_json,updated_at=excluded.updated_at"
                ),
                (assessment_id, diagnostic.model_dump_json(), now),
            )
        self.audit("pronunciation.updated", {"status": diagnostic.status}, assessment_id)

    def get_pronunciation(self, assessment_id: str) -> PronunciationDiagnostic | None:
        with self._connection() as connection:
            row = connection.execute(
                self._query(
                    "SELECT diagnostic_json FROM pronunciation_diagnostics WHERE assessment_id=?"
                ),
                (assessment_id,),
            ).fetchone()
        return None if row is None else PronunciationDiagnostic.model_validate_json(row["diagnostic_json"])

    def audit(
        self,
        event_type: str,
        payload: dict[str, Any],
        assessment_id: str | None = None,
        correlation_id: str = "",
    ) -> None:
        with self._lock, self._connection() as connection, connection:
            connection.execute(
                self._query(
                    "INSERT INTO audit_logs(audit_id,assessment_id,correlation_id,event_type,event_json,created_at) VALUES(?,?,?,?,?,?)"
                ),
                (
                    str(uuid.uuid4()),
                    assessment_id,
                    correlation_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def set_runtime_setting(self, key: str, value: str) -> None:
        with self._lock, self._connection() as connection, connection:
            connection.execute(
                self._query(
                    "INSERT INTO runtime_settings(setting_key,setting_value,updated_at) VALUES(?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at"
                ),
                (key, value, utc_now().isoformat()),
            )

    def get_runtime_setting(self, key: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                self._query("SELECT setting_value FROM runtime_settings WHERE setting_key=?"),
                (key,),
            ).fetchone()
        return None if row is None else str(row["setting_value"])

    def save_fluency_observation(
        self,
        result: FluencyObservationResult,
    ) -> FluencyObservationResult:
        existing = self.get_fluency_observation(result.session_id, result.turn_id)
        if existing is not None:
            return existing
        try:
            with self._lock, self._connection() as connection, connection:
                connection.execute(
                    self._query(
                        "INSERT INTO fluency_observations(session_id,turn_id,mode,result_json,created_at) VALUES(?,?,?,?,?)"
                    ),
                    (
                        result.session_id,
                        result.turn_id,
                        result.mode.value,
                        result.model_dump_json(),
                        utc_now().isoformat(),
                    ),
                )
        except Exception:
            # A concurrent idempotent insert may have won the unique key. Only
            # suppress the error when that exact observation now exists.
            existing = self.get_fluency_observation(result.session_id, result.turn_id)
            if existing is not None:
                return existing
            raise
        return result

    def get_fluency_observation(
        self,
        session_id: str,
        turn_id: str,
    ) -> FluencyObservationResult | None:
        with self._connection() as connection:
            row = connection.execute(
                self._query(
                    "SELECT result_json FROM fluency_observations WHERE session_id=? AND turn_id=?"
                ),
                (session_id, turn_id),
            ).fetchone()
        return (
            None
            if row is None
            else FluencyObservationResult.model_validate_json(row["result_json"])
        )

    def list_fluency_observations(
        self,
        session_id: str,
    ) -> list[FluencyObservationResult]:
        with self._connection() as connection:
            rows = connection.execute(
                self._query(
                    "SELECT result_json FROM fluency_observations WHERE session_id=? ORDER BY created_at,turn_id"
                ),
                (session_id,),
            ).fetchall()
        return [
            FluencyObservationResult.model_validate_json(row["result_json"])
            for row in rows
        ]
