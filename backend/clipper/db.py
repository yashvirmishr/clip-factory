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
    clip_count INTEGER NOT NULL DEFAULT 0,
    reel_quality REAL NOT NULL DEFAULT 0,
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
    policy_version TEXT NOT NULL DEFAULT '',
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

-- Per-clip manual edits live here instead of being written back into the whole
-- analysis payload: a caption tweak on a two-hour VOD should not re-serialise
-- several megabytes of word timings.
CREATE TABLE IF NOT EXISTS clip_edits (
    source_id TEXT NOT NULL,
    clip_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (source_id, clip_id, kind)
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- ---------------------------------------------------------------------------
-- Publishing and personal-performance tables. Additive only: existing
-- databases keep working, and every table is created on first launch.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    handle TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    scopes TEXT NOT NULL DEFAULT '[]',
    capabilities TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'connected',
    token_ref TEXT NOT NULL DEFAULT '',
    client_ref TEXT NOT NULL DEFAULT '',
    token_expires_at REAL NOT NULL DEFAULT 0,
    last_sync_at REAL NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(platform, external_id)
);
CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    captured_at REAL NOT NULL,
    followers INTEGER,
    total_views INTEGER,
    profile_views INTEGER,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_account_snapshots_account ON account_snapshots(account_id, captured_at);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    platform_post_id TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    published_at REAL NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    hashtags TEXT NOT NULL DEFAULT '[]',
    duration_s REAL NOT NULL DEFAULT 0,
    media_path TEXT NOT NULL DEFAULT '',
    clip_id TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    render_id TEXT NOT NULL DEFAULT '',
    policy_version TEXT NOT NULL DEFAULT '',
    market_version TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'app',
    visibility TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'published',
    features TEXT NOT NULL DEFAULT '{}',
    signals TEXT NOT NULL DEFAULT '{}',
    llm TEXT NOT NULL DEFAULT '{}',
    feature_coverage TEXT NOT NULL DEFAULT 'full',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_account ON posts(account_id, published_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_platform
    ON posts(account_id, platform_post_id) WHERE platform_post_id <> '';

CREATE TABLE IF NOT EXISTS post_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    captured_at REAL NOT NULL,
    age_hours REAL NOT NULL DEFAULT 0,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    saves INTEGER,
    watch_time_s REAL,
    avg_view_duration_s REAL,
    impressions INTEGER,
    follows INTEGER,
    profile_visits INTEGER,
    link_clicks INTEGER,
    composite REAL,
    label INTEGER,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_post_metrics_post ON post_metrics(post_id, captured_at);

CREATE TABLE IF NOT EXISTS publish_jobs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    clip_id TEXT NOT NULL DEFAULT '',
    media_path TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    platform_post_id TEXT NOT NULL DEFAULT '',
    post_url TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publish_jobs_status ON publish_jobs(status, next_attempt_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_jobs_idem
    ON publish_jobs(idempotency_key) WHERE idempotency_key <> '';

CREATE TABLE IF NOT EXISTS personal_models (
    version TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    payload TEXT NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 0,
    data_window TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS suggestions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL DEFAULT '',
    clip_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    fix TEXT NOT NULL DEFAULT '',
    auto_fixable INTEGER NOT NULL DEFAULT 0,
    action TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suggestions_clip ON suggestions(source_id, clip_id, status);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    hypothesis TEXT NOT NULL DEFAULT '',
    post_id TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
    version TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    payload TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0
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
        try:
            conn.execute("ALTER TABLE decisions ADD COLUMN policy_version TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # The source list reads these instead of parsing every stored payload.
        # A database that predates them is backfilled once, here.
        added_summary = False
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN signals TEXT NOT NULL DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE posts ADD COLUMN llm TEXT NOT NULL DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE analyses ADD COLUMN clip_count INTEGER NOT NULL DEFAULT 0")
            added_summary = True
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE analyses ADD COLUMN reel_quality REAL NOT NULL DEFAULT 0")
            added_summary = True
        except sqlite3.OperationalError:
            pass
        if added_summary:
            rows = conn.execute("SELECT source_id, payload FROM analyses").fetchall()
            for row in rows:
                try:
                    stored = AnalysisResult.model_validate_json(row["payload"])
                except ValueError:
                    continue
                conn.execute(
                    "UPDATE analyses SET clip_count=?, reel_quality=? WHERE source_id=?",
                    (
                        sum(1 for c in stored.candidates if c.rank),
                        float(stored.reel_quality),
                        row["source_id"],
                    ),
                )


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
            INSERT INTO analyses
                (source_id, payload, asr_backend, llm_backend, clip_count, reel_quality, created_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
                payload=excluded.payload, asr_backend=excluded.asr_backend,
                llm_backend=excluded.llm_backend, clip_count=excluded.clip_count,
                reel_quality=excluded.reel_quality, created_at=excluded.created_at
            """,
            (
                result.source.id,
                result.model_dump_json(),
                result.asr_backend,
                result.llm_backend,
                sum(1 for c in result.candidates if c.rank),
                float(result.reel_quality),
                time.time(),
            ),
        )
    _ANALYSIS_CACHE.pop(result.source.id, None)


# Validating a multi-megabyte payload costs more than the query that fetched it,
# and one request can ask for the same analysis several times (find_candidate,
# captions, trim). Keyed on the row's created_at so an analysis run invalidates
# it without any bookkeeping.
_ANALYSIS_CACHE: dict[str, tuple[float, AnalysisResult]] = {}
_MAX_CACHED_ANALYSES = 4


def get_analysis(source_id: str) -> AnalysisResult | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT created_at FROM analyses WHERE source_id=?", (source_id,)
        ).fetchone()
        if row is None:
            _ANALYSIS_CACHE.pop(source_id, None)
            return None
        stamp = float(row["created_at"])
        cached = _ANALYSIS_CACHE.get(source_id)
        if cached is not None and cached[0] == stamp:
            # Only the stamp is a few bytes; the payload can be megabytes, so it
            # is fetched below and only when this process has to parse it.
            return cached[1]
        payload = conn.execute(
            "SELECT payload FROM analyses WHERE source_id=?", (source_id,)
        ).fetchone()
    if payload is None:
        _ANALYSIS_CACHE.pop(source_id, None)
        return None
    result = AnalysisResult.model_validate_json(payload["payload"])
    _apply_clip_edits(result)
    if len(_ANALYSIS_CACHE) >= _MAX_CACHED_ANALYSES and source_id not in _ANALYSIS_CACHE:
        _ANALYSIS_CACHE.clear()
    _ANALYSIS_CACHE[source_id] = (stamp, result)
    return result


def save_clip_edit(source_id: str, clip_id: str, kind: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO clip_edits (source_id, clip_id, kind, payload, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(source_id, clip_id, kind) DO UPDATE SET
                payload=excluded.payload, updated_at=excluded.updated_at
            """,
            (source_id, clip_id, kind, json.dumps(payload), time.time()),
        )
    _ANALYSIS_CACHE.pop(source_id, None)


def clear_clip_edits(source_id: str, clip_id: str | None = None, kind: str | None = None) -> None:
    query = "DELETE FROM clip_edits WHERE source_id=?"
    args: list[object] = [source_id]
    if clip_id is not None:
        query += " AND clip_id=?"
        args.append(clip_id)
    if kind is not None:
        query += " AND kind=?"
        args.append(kind)
    with connect() as conn:
        conn.execute(query, tuple(args))
    _ANALYSIS_CACHE.pop(source_id, None)


def _apply_clip_edits(analysis: AnalysisResult) -> None:
    """Fold stored per-clip edits onto a freshly parsed analysis."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT clip_id, kind, payload FROM clip_edits WHERE source_id=?",
            (analysis.source.id,),
        ).fetchall()
    if not rows:
        return
    candidates = {clip.id: clip for clip in analysis.candidates}
    for row in rows:
        candidate = candidates.get(row["clip_id"])
        if candidate is None:
            continue
        try:
            payload = json.loads(row["payload"])
        except ValueError:
            continue
        if row["kind"] == "captions":
            pages = payload.get("pages")
            if isinstance(pages, list):
                candidate.caption_pages = pages
        elif row["kind"] == "hook":
            hook = payload.get("hook")
            if isinstance(hook, str) and candidate.llm is not None:
                candidate.llm = candidate.llm.model_copy(update={"hook": hook})
        elif row["kind"] == "caption_style":
            overrides = payload.get("overrides")
            if isinstance(overrides, dict):
                # New shape keeps the chosen preset with the overrides; an older
                # row has only the flat override dict and still loads.
                stored = {"overrides": dict(overrides)}
                if payload.get("preset"):
                    stored["preset"] = str(payload["preset"])
                candidate.caption_style = stored
            elif payload.get("preset"):
                candidate.caption_style = {"preset": str(payload["preset"])}
            else:
                candidate.caption_style = dict(payload)


def list_sources_with_stats() -> list[dict]:
    """The source rail: one query, no payload parsing."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*, a.source_id AS analyzed_id,
                   COALESCE(a.clip_count, 0) AS clip_count,
                   COALESCE(a.reel_quality, 0) AS reel_quality
            FROM sources s
            LEFT JOIN analyses a ON a.source_id = s.id
            ORDER BY s.created_at DESC
            """
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        info = SourceInfo(
            id=r["id"], name=r["name"], path=r["path"], duration=r["duration"],
            width=r["width"], height=r["height"], fps=r["fps"],
            has_audio=bool(r["has_audio"]), size_bytes=r["size_bytes"],
            origin_url=r["origin_url"] if "origin_url" in r.keys() else "",
        )
        out.append(
            {
                **info.model_dump(),
                "analyzed": r["analyzed_id"] is not None,
                "clip_count": int(r["clip_count"] or 0),
                "reel_quality": float(r["reel_quality"] or 0.0),
            }
        )
    return out


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
    from .policy import active as active_policy

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO decisions
                (candidate_id, source_id, action, reason, hook, text, fused, final,
                 llm_score, llm, features, signals, model_version, policy_version,
                 prompt_version, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                active_policy().version,
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
