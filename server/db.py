"""SQLite persistence for completed runs (shareable replay URLs)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "runs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    params     TEXT NOT NULL,
    summary    TEXT,
    graph      TEXT,
    timeline   TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def save_run(run_id: str, params: dict, summary: dict,
             graph: dict, timeline: list[dict]) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, datetime.now(timezone.utc).isoformat(),
             json.dumps(params), json.dumps(summary),
             json.dumps(graph), json.dumps(timeline)))


def get_run(run_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, params, summary, graph, timeline "
            "FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "created_at": row[1], "status": "complete",
        "params": json.loads(row[2]), "summary": json.loads(row[3] or "null"),
        "graph": json.loads(row[4] or "null"),
        "timeline": json.loads(row[5] or "[]"),
    }


def list_runs(limit: int = 30) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, params, summary FROM runs "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r[0], "created_at": r[1], "status": "complete",
             "params": json.loads(r[2]), "summary": json.loads(r[3] or "null")}
            for r in rows]
