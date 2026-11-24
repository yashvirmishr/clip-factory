"""SQLite persistence.

WAL mode, one connection per operation, no ORM. Every write is small and the
whole database stays well under a few MB for hundreds of hours of analysis,
which matters when the machine only has 16 GB shared with the GPU.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import SETTINGS
from .domain import AnalysisResult, ClipCandidate, SourceInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    fps REAL NOT NULL DEFAULT 0,
    has_audio INTEGER NOT NULL DEFAULT 1,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    origin_url TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    source_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    asr_backend TEXT NOT NULL,
    llm_backend TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    hook TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    fused REAL NOT NULL DEFAULT 0,
    final REAL NOT NULL DEFAULT 0,
    llm_score INTEGER,
    llm TEXT NOT NULL DEFAULT '{}',
    features TEXT NOT NULL DEFAULT '{}',
    signals TEXT NOT NULL DEFAULT '{}',
    model_version TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT 'v1',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);

CREATE TABLE IF NOT EXISTS hook_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    before TEXT NOT NULL,
    after TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or SETTINGS.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Forward-compatible: older databases predate the llm column.
        try:
            conn.execute("ALTER TABLE decisions ADD COLUMN llm TEXT NOT NULL DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE sources ADD COLUMN origin_url TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def upsert_source(info: SourceInfo) -> SourceInfo:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO sources (id, name, path, duration, width, height, fps, has_audio, size_bytes, origin_url, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, path=excluded.path, duration=excluded.duration,
                width=excluded.width, height=excluded.height, fps=excluded.fps,
                has_audio=excluded.has_audio, size_bytes=excluded.size_bytes,
                origin_url=excluded.origin_url
            """,
            (
                info.id, info.name, info.path, info.duration, info.width, info.height,
                info.fps, int(info.has_audio), info.size_bytes, info.origin_url, time.time(),
            ),
        )
    return info


def get_source(source_id: str) -> SourceInfo | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if row is None:
        return None
    return SourceInfo(
        id=row["id"], name=row["name"], path=row["path"], duration=row["duration"],
        width=row["width"], height=row["height"], fps=row["fps"],
        has_audio=bool(row["has_audio"]), size_bytes=row["size_bytes"],
        origin_url=row["origin_url"] if "origin_url" in row.keys() else "",
    )


def list_sources() -> list[SourceInfo]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
    return [
        SourceInfo(
            id=r["id"], name=r["name"], path=r["path"], duration=r["duration"],
            width=r["width"], height=r["height"], fps=r["fps"],
            has_audio=bool(r["has_audio"]), size_bytes=r["size_bytes"],
            origin_url=r["origin_url"] if "origin_url" in r.keys() else "",
        )
        for r in rows
    ]


def save_analysis(result: AnalysisResult) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO analyses (source_id, payload, asr_backend, llm_backend, created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
                payload=excluded.payload, asr_backend=excluded.asr_backend,
                llm_backend=excluded.llm_backend, created_at=excluded.created_at
            """,
            (
                result.source.id,
                result.model_dump_json(),
                result.asr_backend,
                result.llm_backend,
                time.time(),
            ),
        )


def get_analysis(source_id: str) -> AnalysisResult | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT payload FROM analyses WHERE source_id=?", (source_id,)
        ).fetchone()
    if row is None:
        return None
    return AnalysisResult.model_validate_json(row["payload"])


def has_analysis(source_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM analyses WHERE source_id=?", (source_id,)
        ).fetchone()
    return row is not None


def find_candidate(source_id: str, candidate_id: str) -> ClipCandidate | None:
    analysis = get_analysis(source_id)
    if analysis is None:
        return None
    return next((c for c in analysis.candidates if c.id == candidate_id), None)


def record_decision(candidate: ClipCandidate, action: str, reason: str = "") -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO decisions
                (candidate_id, source_id, action, reason, hook, text, fused, final,
                 llm_score, llm, features, signals, model_version, prompt_version, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                candidate.id,
                candidate.source_id,
                action,
                reason,
                (candidate.llm.hook if candidate.llm else ""),
                candidate.text,
                candidate.fused,
                candidate.final,
                (candidate.llm.score if candidate.llm else None),
                (candidate.llm.model_dump_json() if candidate.llm else "{}"),
                json.dumps(candidate.features.model_dump() if candidate.features else {}),
                json.dumps(candidate.signals),
                (candidate.llm.provider if candidate.llm else ""),
                "v1",
                time.time(),
            ),
        )


def list_decisions(limit: int = 5000) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        for key in ("features", "signals", "llm"):
            try:
                item[key] = json.loads(item[key])
            except (json.JSONDecodeError, TypeError):
                item[key] = {}
        out.append(item)
    return out


def decision_count() -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()
    return int(row["n"]) if row else 0


def record_hook_edit(before: str, after: str) -> None:
    if before.strip() == after.strip():
        return
    with connect() as conn:
        conn.execute(
            "INSERT INTO hook_edits (before, after, created_at) VALUES (?,?,?)",
            (before, after, time.time()),
        )


def list_hook_edits(limit: int = 2000) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM hook_edits ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_state(key: str, default: object = None) -> object:
    with connect() as conn:
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default


def set_state(key: str, value: object) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO state (key, value, updated_at) VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value), time.time()),
        )
