"""Job orchestrator stub — SQLite-persisted queue (F0)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from forge.paths import find_repo_root
from forge.telemetry import TelemetryStore, make_system_event


class JobState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class Job:
    id: str
    kind: str
    state: JobState
    payload: dict[str, Any]
    created_at: str
    updated_at: str
    error: str | None = None


class JobOrchestrator:
    """Minimal queue. Generators register in F1+; F0 proves persistence + lifecycle."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or find_repo_root()
        self.db_path = self.root / ".fabric" / "jobs" / "orchestrator.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.telemetry = TelemetryStore(self.root)
        self._ensure_db()

    def _ensure_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  state TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  error TEXT
                )
                """
            )
            conn.commit()

    def enqueue(self, kind: str, payload: dict[str, Any] | None = None) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        job = Job(
            id=str(uuid.uuid4()),
            kind=kind,
            state=JobState.QUEUED,
            payload=payload or {},
            created_at=now,
            updated_at=now,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO jobs(id, kind, state, payload_json, created_at, updated_at, error)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (job.id, job.kind, job.state.value, json.dumps(job.payload), now, now),
            )
            conn.commit()
        self.telemetry.emit(
            make_system_event(
                "job.enqueued",
                agent_id="orchestrator",
                agent_type="orchestrator",
                action_taken={"job_id": job.id, "kind": kind},
                action_source="system",
            )
        )
        return job

    def list_jobs(self, limit: int = 50) -> list[Job]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, kind, state, payload_json, created_at, updated_at, error
                FROM jobs ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            Job(
                id=r[0],
                kind=r[1],
                state=JobState(r[2]),
                payload=json.loads(r[3]),
                created_at=r[4],
                updated_at=r[5],
                error=r[6],
            )
            for r in rows
        ]

    def health(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return {"db": str(self.db_path.relative_to(self.root)), "job_count": int(n)}
