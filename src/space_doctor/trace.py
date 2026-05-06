from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TraceWriter:
    """Write a small custom JSONL side trace for deterministic demo artifacts.

    Hub trace viewing is best with native Codex, Claude Code, or Pi session JSONL.
    This side trace is still useful as a compact machine-readable run ledger.
    """

    def __init__(self, path: Path, *, run_id: str | None = None) -> None:
        self.path = path
        self.run_id = run_id or str(uuid.uuid4())
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **payload: Any) -> None:
        row = {
            "timestamp": utc_now(),
            "type": "space_doctor_event",
            "run_id": self.run_id,
            "event": event,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def latest_codex_session(root: Path | None = None) -> Path | None:
    root = root or Path.home() / ".codex" / "sessions"
    if not root.exists():
        return None
    files = list(root.rglob("*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def copy_agent_session_trace(source: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    shutil.copy2(source, destination)
    return destination
