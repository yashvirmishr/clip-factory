"""Durable publish queue.

The API enqueues a target, the shared job runner executes it, and the row is
the source of truth if the app restarts. Idempotency and retry state live in
SQLite; tokens never do.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .. import accounts, db, secrets
from ..domain import stable_id
from .base import PublishError, PublishResult, UploadRequest
from .limits import MediaInfo, probe_media
from .youtube import YouTubeAdapter

Progress = Callable[[str, float, str], None]


class PublishCancelled(RuntimeError):
    pass


def _json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _row_to_job(row) -> dict:
    metadata = _json(row["metadata"], {})
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "platform": row["platform"],
        "account_id": row["account_id"],
        "source_id": row["source_id"],
        "clip_id": row["clip_id"],
        "media_path": row["media_path"],
        "metadata": metadata,
        "idempotency_key": row["idempotency_key"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
        "next_attempt_at": row["next_attempt_at"],
        "platform_post_id": row["platform_post_id"],
        "post_url": row["post_url"],
        "error": row["error"],
        "error_code": row["error_code"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "elapsed": round(row["updated_at"] - row["created_at"], 2),
    }


def enqueue(
    *,
    platform: str,
    account_id: str,
    media_path: str | Path,
    metadata: dict[str, Any],
    source_id: str = "",
    clip_id: str = "",
    idempotency_key: str = "",
    batch_id: str = "",
    max_attempts: int = 3,
    job_id: str = "",
) -> dict:
    account = accounts.get_account(account_id)
    if account is None:
        raise ValueError("That account is not connected.")
    if account.platform != platform:
        raise ValueError("The selected account belongs to a different platform.")
    path = Path(media_path)
    if not path.exists() or not path.is_file():
        raise ValueError(f"Rendered file not found: {path}")
    if idempotency_key:
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM publish_jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
        if existing is not None:
            return _row_to_job(existing)
    now = time.time()
    job_id = job_id or f"pub_{uuid.uuid4().hex[:12]}"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO publish_jobs
                (id, batch_id, platform, account_id, source_id, clip_id, media_path,
                 metadata, idempotency_key, status, stage, progress, attempts,
                 max_attempts, next_attempt_at, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id, batch_id, platform, account_id, source_id, clip_id, str(path.resolve()),
                json.dumps(metadata), idempotency_key, "queued", "", 0.0, 0,
                max(1, int(max_attempts)), 0.0, now, now,
            ),
        )
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row)


def get_job(job_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(limit: int = 50, status: str | None = None) -> list[dict]:
    with db.connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM publish_jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, max(1, limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM publish_jobs ORDER BY created_at DESC LIMIT ?", (max(1, limit),)
            ).fetchall()
    return [_row_to_job(row) for row in rows]


def claim_next(now: float | None = None) -> dict | None:
    now = now or time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM publish_jobs
            WHERE status IN ("queued", "retry") AND next_attempt_at <= ?
            ORDER BY created_at ASC LIMIT 1
            """,
            (now,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE publish_jobs SET status=?, stage=?, attempts=attempts+1, updated_at=? WHERE id=?",
            ("running", "starting", now, row["id"]),
        )
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (row["id"],)).fetchone()
    return _row_to_job(row)


def update_progress(job_id: str, stage: str, pct: float, detail: str = "") -> None:
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise PublishCancelled("The publish job disappeared.")
        if row["status"] == "cancelling":
            conn.execute(
                "UPDATE publish_jobs SET status=?, stage=?, error=?, updated_at=? WHERE id=?",
                ("cancelled", "cancelled", "Cancelled by the user", time.time(), job_id),
            )
            raise PublishCancelled("Cancelled by the user.")
        conn.execute(
            "UPDATE publish_jobs SET stage=?, progress=?, updated_at=? WHERE id=?",
            (stage[:80], max(0.0, min(1.0, float(pct))), time.time(), job_id),
        )


def _post_id(account_id: str, platform_post_id: str) -> str:
    return "post_" + stable_id(account_id, platform_post_id)


def mark_done(job_id: str, result: PublishResult) -> dict:
    now = time.time()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise PublishError("The publish job disappeared.", code="missing_job")
        metadata = _json(row["metadata"], {})
        conn.execute(
            """
            UPDATE publish_jobs SET status=?, stage=?, progress=1, platform_post_id=?,
                post_url=?, error=?, error_code=?, updated_at=? WHERE id=?
            """,
            ("done", "done", result.platform_post_id, result.url, "", "", now, job_id),
        )
        post_id = _post_id(row["account_id"], result.platform_post_id)
        conn.execute(
            """
            INSERT INTO posts
                (id, account_id, platform_post_id, url, published_at, title, caption,
                 hashtags, duration_s, media_path, clip_id, source_id, render_id,
                 policy_version, market_version, origin, visibility, status, features,
                 feature_coverage, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                url=excluded.url, title=excluded.title, caption=excluded.caption,
                hashtags=excluded.hashtags, duration_s=excluded.duration_s,
                visibility=excluded.visibility, status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (
                post_id, row["account_id"], result.platform_post_id, result.url, now,
                str(metadata.get("title", "") or ""),
                str(metadata.get("description", metadata.get("caption", "")) or ""),
                json.dumps(metadata.get("tags", metadata.get("hashtags", [])) or []),
                float(metadata.get("duration_s", 0) or 0),
                row["media_path"], row["clip_id"], row["source_id"],
                str(metadata.get("render_id", "") or ""),
                str(metadata.get("policy_version", "") or ""),
                str(metadata.get("market_version", "") or ""),
                "app", str(metadata.get("visibility", "") or ""), "published",
                json.dumps(metadata.get("features", {}) or {}),
                str(metadata.get("feature_coverage", "full") or "full"),
                now, now,
            ),
        )
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row)


def mark_failure(job_id: str, error: str, *, code: str = "", retryable: bool = False) -> dict:
    now = time.time()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise PublishError("The publish job disappeared.", code="missing_job")
        attempts = int(row["attempts"])
        can_retry = retryable and attempts < int(row["max_attempts"])
        if can_retry:
            delay = min(3600.0, 60.0 * (2 ** max(0, attempts - 1)))
            conn.execute(
                """
                UPDATE publish_jobs SET status=?, stage=?, error=?, error_code=?,
                    next_attempt_at=?, updated_at=? WHERE id=?
                """,
                ("retry", "waiting to retry", error[:1000], code[:80], now + delay, now, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE publish_jobs SET status=?, stage=?, error=?, error_code=?, updated_at=? WHERE id=?
                """,
                ("error", "failed", error[:1000], code[:80], now, job_id),
            )
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row)


def retry(job_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        if row["status"] == "running":
            raise ValueError("That upload is still running.")
        conn.execute(
            """
            UPDATE publish_jobs SET status=?, stage=?, progress=0, attempts=0,
                next_attempt_at=0, error=?, error_code=?, updated_at=? WHERE id=?
            """,
            ("queued", "", "", "", time.time(), job_id),
        )
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row)


def cancel(job_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        if row["status"] in ("done", "error", "cancelled"):
            return get_job(job_id)
        target = "cancelling" if row["status"] == "running" else "cancelled"
        conn.execute(
            "UPDATE publish_jobs SET status=?, stage=?, updated_at=? WHERE id=?",
            (target, "cancelling" if target == "cancelling" else "cancelled", time.time(), job_id),
        )
        row = conn.execute("SELECT * FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(row)


def adapter_for(platform: str):
    if platform == "youtube":
        return YouTubeAdapter()
    raise PublishError(
        f"{platform.title()} publishing is not enabled yet. Use Export & share for now.",
        code="adapter_unavailable",
    )


def _upload_request(job: dict) -> UploadRequest:
    metadata = job["metadata"]
    path = Path(job["media_path"])
    media = metadata.get("media") if isinstance(metadata.get("media"), dict) else None
    info = MediaInfo(**media) if media else probe_media(path)
    tags = metadata.get("tags", metadata.get("hashtags", []))
    if not isinstance(tags, list):
        tags = []
    return UploadRequest(
        account_id=job["account_id"],
        media_path=job["media_path"],
        title=str(metadata.get("title", "") or ""),
        description=str(metadata.get("description", metadata.get("caption", "")) or ""),
        tags=[str(tag) for tag in tags],
        visibility=str(metadata.get("visibility", "private") or "private"),
        made_for_kids=bool(metadata.get("made_for_kids", False)),
        publish_at=str(metadata.get("publish_at", "") or ""),
        category_id=str(metadata.get("category_id", "22") or "22"),
        cover_path=str(metadata.get("cover_path", "") or ""),
        public_url=str(metadata.get("public_url", "") or ""),
        media=info,
        extra=metadata,
    )


def process(job_id: str, progress: Progress | None = None) -> dict:
    progress = progress or (lambda stage, pct, detail="": None)
    job = get_job(job_id)
    if job is None:
        raise PublishError("That publish job does not exist.", code="missing_job")
    if job["status"] not in ("running", "queued", "retry"):
        raise PublishError("Publish job is " + str(job["status"]) + ".", code="bad_state")
    token = accounts.access_token(job["account_id"])
    request = _upload_request(job)
    adapter = adapter_for(job["platform"])

    def report(stage: str, pct: float, detail: str = "") -> None:
        update_progress(job_id, stage, pct, detail)
        progress(stage, pct, detail)

    try:
        result = adapter.upload(request, token, report)
    except PublishError as exc:
        mark_failure(job_id, str(exc), code=exc.code, retryable=exc.retryable)
        raise
    except Exception as exc:  # noqa: BLE001 - queue must persist the failure
        mark_failure(job_id, f"{type(exc).__name__}: {exc}", code="unexpected", retryable=False)
        raise
    return mark_done(job_id, result)


def next_pending(now: float | None = None) -> dict | None:
    """Return the next due job without claiming it (diagnostics/UI)."""
    now = now or time.time()
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM publish_jobs
            WHERE status IN ("queued", "retry") AND next_attempt_at <= ?
            ORDER BY created_at ASC LIMIT 1
            """,
            (now,),
        ).fetchone()
    return _row_to_job(row) if row else None
