"""Telemetry event schema validation and append-only JSONL store (F0 stub)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, Field

from forge.paths import find_repo_root, schema_dir


class TelemetryEvent(BaseModel):
    """Logical event — SPEC §5.4 minimum fields."""

    schema_version: str = "1.0"
    timestamp: str
    agent_id: str
    agent_type: str
    event_type: str
    state_before: dict[str, Any] | None = None
    state_after: dict[str, Any] | None = None
    action_taken: str | dict[str, Any] | None = None
    action_source: str | None = None
    inference_latency_ms: float | None = None
    model_id: str | None = None
    model_version: str | None = None
    thought_stream: Any = None
    sandbox_id: str | None = None
    profile: str | None = None
    sim_tick: int | None = None
    state_hash: str | None = None
    locale_key: str | None = None


def load_event_schema(root: Path | None = None) -> dict[str, Any]:
    path = schema_dir(root) / "telemetry.event.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_event(event: dict[str, Any], root: Path | None = None) -> list[str]:
    errors: list[str] = []
    try:
        jsonschema.validate(instance=event, schema=load_event_schema(root))
    except jsonschema.ValidationError as exc:
        errors.append(exc.message)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    return errors


def make_system_event(
    event_type: str,
    *,
    agent_id: str = "forge",
    agent_type: str = "system",
    **kwargs: Any,
) -> TelemetryEvent:
    return TelemetryEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        agent_id=agent_id,
        agent_type=agent_type,
        event_type=event_type,
        **kwargs,
    )


class TelemetryStore:
    """Append-only JSONL under .fabric/telemetry/ — SQLite/DuckDB arrive later."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or find_repo_root()
        self.path = self.root / ".fabric" / "telemetry" / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: TelemetryEvent | dict[str, Any]) -> None:
        if isinstance(event, TelemetryEvent):
            payload = event.model_dump(mode="json")
        else:
            payload = event
        errs = validate_event(payload, self.root)
        if errs:
            raise ValueError(f"invalid telemetry event: {errs}")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
