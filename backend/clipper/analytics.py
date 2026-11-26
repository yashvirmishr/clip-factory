"""Own-account analytics: pull posts, normalize engagement, label performance.

The goal is not a virality forecast. It is a per-account baseline: which of
*your* clips beat *your* normal, and which features show up in the winners.
Every number here is derived from the platform response or a documented
formula, and cross-account comparisons are deliberately not made.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import time
from typing import Any

from . import accounts
from .domain import stable_id
from .publish.base import PublishError, RemotePost
from .publish.limits import limits_for

MIN_AGE_HOURS = 24.0
MIN_VIEWS = 50
MIN_POSTS_FOR_LABELS = 8

HASHTAG_RE = re.compile(r"#([\w]+)", re.UNICODE)


def _num(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _hashtags(caption: str) -> list[str]:
    return [f"#{match}" for match in HASHTAG_RE.findall(caption or "")][:60]


def engagement_rate(metrics: dict[str, Any]) -> float:
    """Weighted interactions per view. The label signal for the personal model."""
    views = _num(metrics.get("views"))
    if not views:
        return 0.0
    weighted = (
        _num(metrics.get("likes"))
        + 2.5 * _num(metrics.get("comments"))
        + 4.0 * _num(metrics.get("shares"))
        + 3.0 * _num(metrics.get("saves"))
    )
    return round(weighted / views, 6)


def composite_score(metrics: dict[str, Any], duration_s: float = 0.0, age_hours: float = 0.0) -> float:
    """A stable 0..100 score that rewards reach *and* interaction.

    Reach uses log1p so one outlier cannot dominate. Engagement is normalized
    by views, then capped so a single like on a 10-view post is not treated as
    a 10% hit. Retention is included only when the platform reports it.
    """
    views = _num(metrics.get("views"))
    likes = _num(metrics.get("likes"))
    comments = _num(metrics.get("comments"))
    shares = _num(metrics.get("shares"))
    saves = _num(metrics.get("saves"))
    reach = min(1.0, math.log1p(views) / math.log1p(10_000))
    weighted = likes + 2.5 * comments + 4.0 * shares + 3.0 * saves
    engagement = min(1.0, (weighted / views) * 40.0) if views else 0.0
    velocity = 0.0
    if age_hours > 0 and views:
        velocity = min(1.0, math.log1p(views / age_hours) / math.log1p(500))
    retention = 0.0
    avg = metrics.get("avg_view_duration_s")
    if avg is not None and duration_s > 0:
        try:
            retention = max(0.0, min(1.0, float(avg) / duration_s))
        except (TypeError, ValueError):
            retention = 0.0
    score = 0.45 * reach + 0.27 * engagement + 0.18 * retention + 0.10 * velocity
    return round(100.0 * score, 3)


def _parse_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _row_to_post(row) -> dict:
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "platform_post_id": row["platform_post_id"],
        "url": row["url"],
        "published_at": row["published_at"],
        "title": row["title"],
        "caption": row["caption"],
        "hashtags": _parse_json(row["hashtags"], []),
        "duration_s": row["duration_s"],
        "clip_id": row["clip_id"],
        "source_id": row["source_id"],
        "origin": row["origin"],
        "features": _parse_json(row["features"], {}),
        "feature_coverage": row["feature_coverage"],
        "policy_version": row["policy_version"],
        "metrics": {},
        "label": None,
        "composite": None,
        "engagement_rate": 0.0,
        "captured_at": 0.0,
    }


def list_posts(account_id: str = "", limit: int = 100) -> list[dict]:
    """Posts plus their latest captured metrics, newest first."""
    where = "WHERE p.account_id=?" if account_id else ""
    params: tuple[Any, ...] = (account_id,) if account_id else ()
    with accounts.db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT p.*, m.captured_at AS m_captured_at, m.age_hours AS m_age_hours,
                   m.views AS m_views, m.likes AS m_likes, m.comments AS m_comments,
                   m.shares AS m_shares, m.saves AS m_saves,
                   m.avg_view_duration_s AS m_avg, m.impressions AS m_impressions,
                   m.follows AS m_follows, m.profile_visits AS m_profile_visits,
                   m.link_clicks AS m_link_clicks, m.composite AS m_composite,
                   m.label AS m_label
            FROM posts p
            LEFT JOIN post_metrics m ON m.id = (
                SELECT id FROM post_metrics WHERE post_id=p.id ORDER BY captured_at DESC, id DESC LIMIT 1
            )
            {where}
            ORDER BY p.published_at DESC, p.created_at DESC LIMIT ?
            """,
            params + (max(1, int(limit)),),
        ).fetchall()
    out = []
    for row in rows:
        post = _row_to_post(row)
        if row["m_captured_at"] is not None:
            post["captured_at"] = row["m_captured_at"]
            post["composite"] = row["m_composite"]
            post["label"] = row["m_label"]
            post["metrics"] = {
                "views": row["m_views"], "likes": row["m_likes"],
                "comments": row["m_comments"], "shares": row["m_shares"],
                "saves": row["m_saves"], "avg_view_duration_s": row["m_avg"],
                "impressions": row["m_impressions"], "follows": row["m_follows"],
                "profile_visits": row["m_profile_visits"], "link_clicks": row["m_link_clicks"],
                "age_hours": row["m_age_hours"],
            }
            post["engagement_rate"] = engagement_rate(post["metrics"])
        out.append(post)
    return out


def _eligible(post: dict, now: float) -> bool:
    age = max(0.0, (now - float(post["published_at"] or 0)) / 3600.0)
    return age >= MIN_AGE_HOURS and _num(post["metrics"].get("views")) >= MIN_VIEWS


def baseline(account_id: str, now: float | None = None) -> dict:
    now = now or time.time()
    posts = [p for p in list_posts(account_id, limit=500) if _eligible(p, now)]
    scores = [float(p["composite"]) for p in posts if p.get("composite") is not None]
    rates = [float(p["engagement_rate"]) for p in posts]
    return {
        "account_id": account_id,
        "eligible_posts": len(posts),
        "median_composite": round(statistics.median(scores), 3) if scores else 0.0,
        "mean_composite": round(statistics.fmean(scores), 3) if scores else 0.0,
        "median_engagement_rate": round(statistics.median(rates), 6) if rates else 0.0,
        "median_views": int(statistics.median([_num(p["metrics"].get("views")) for p in posts])) if posts else 0,
        "labels_ready": len([r for r in rates if r > 0]) >= MIN_POSTS_FOR_LABELS,
    }


def _refresh_labels(account_id: str, now: float) -> dict:
    posts = [p for p in list_posts(account_id, limit=500) if _eligible(p, now)]
    rates = [float(p["engagement_rate"]) for p in posts if float(p["engagement_rate"]) > 0]
    if len(rates) < MIN_POSTS_FOR_LABELS:
        with accounts.db.connect() as conn:
            conn.execute(
                "UPDATE post_metrics SET label=NULL WHERE post_id IN (SELECT id FROM posts WHERE account_id=?)",
                (account_id,),
            )
        return {"labeled": 0, "positives": 0, "negatives": 0, "median": 0.0}
    median = statistics.median(rates)
    labeled = positives = negatives = 0
    with accounts.db.connect() as conn:
        for post in posts:
            rate = float(post["engagement_rate"])
            label = None if rate <= 0 else (1 if rate >= median else 0)
            latest = conn.execute(
                "SELECT id FROM post_metrics WHERE post_id=? ORDER BY captured_at DESC, id DESC LIMIT 1",
                (post["id"],),
            ).fetchone()
            if latest is None:
                continue
            conn.execute("UPDATE post_metrics SET label=? WHERE id=?", (label, latest["id"]))
            if label is not None:
                labeled += 1
                positives += 1 if label == 1 else 0
                negatives += 1 if label == 0 else 0
    return {"labeled": labeled, "positives": positives, "negatives": negatives, "median": round(median, 6)}


def _upsert_remote(account_id: str, remote: RemotePost, now: float) -> tuple[str, bool]:
    post_id = "post_" + stable_id(account_id, remote.platform_post_id)
    caption = remote.caption or ""
    with accounts.db.connect() as conn:
        existing = conn.execute("SELECT id FROM posts WHERE id=?", (post_id,)).fetchone()
        conn.execute(
            """
            INSERT INTO posts
                (id, account_id, platform_post_id, url, published_at, title, caption,
                 hashtags, duration_s, media_path, clip_id, source_id, render_id,
                 policy_version, market_version, origin, visibility, status, features,
                 feature_coverage, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                url=CASE WHEN posts.url='' THEN excluded.url ELSE posts.url END,
                published_at=CASE WHEN posts.published_at=0 THEN excluded.published_at ELSE posts.published_at END,
                title=CASE WHEN posts.title='' THEN excluded.title ELSE posts.title END,
                caption=CASE WHEN posts.caption='' THEN excluded.caption ELSE posts.caption END,
                hashtags=CASE WHEN posts.hashtags='[]' THEN excluded.hashtags ELSE posts.hashtags END,
                duration_s=CASE WHEN posts.duration_s=0 THEN excluded.duration_s ELSE posts.duration_s END,
                updated_at=excluded.updated_at
            """,
            (
                post_id, account_id, remote.platform_post_id, remote.url,
                float(remote.published_at or now), remote.title or "", caption,
                json.dumps(_hashtags(caption)), float(remote.duration_s or 0),
                "", "", "", "", "", "", "external", "", "published", "{}", "none",
                now, now,
            ),
        )
    return post_id, existing is None


def _capture_metrics(post_id: str, post: dict, remote: RemotePost, now: float) -> dict:
    published = float(post["published_at"] or now)
    age_hours = max(0.0, (now - published) / 3600.0)
    raw = dict(remote.metrics or {})
    metrics = {key: _num(raw.get(key)) for key in ("views", "likes", "comments", "shares", "saves")}
    for key in ("impressions", "follows", "profile_visits", "link_clicks"):
        metrics[key] = _num(raw.get(key))
    for key in ("avg_view_duration_s", "watch_time_s"):
        value = raw.get(key)
        try:
            metrics[key] = max(0.0, float(value)) if value is not None else None
        except (TypeError, ValueError):
            metrics[key] = None
    score = composite_score(metrics, float(post.get("duration_s") or 0), age_hours)
    with accounts.db.connect() as conn:
        conn.execute(
            """
            INSERT INTO post_metrics
                (post_id, captured_at, age_hours, views, likes, comments, shares, saves,
                 watch_time_s, avg_view_duration_s, impressions, follows, profile_visits,
                 link_clicks, composite, label, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (post_id, now, age_hours, metrics["views"], metrics["likes"], metrics["comments"],
             metrics["shares"], metrics["saves"], metrics.get("watch_time_s"),
             metrics.get("avg_view_duration_s"), metrics.get("impressions"),
             metrics.get("follows"), metrics.get("profile_visits"), metrics.get("link_clicks"),
             score, None, json.dumps(raw)),
        )
    return {"composite": score, "age_hours": age_hours, **metrics}


def sync_account(account_id: str, adapter: Any = None, now: float | None = None) -> dict:
    """Fetch recent posts and snapshot their current metrics.

    A failed platform call is recorded on the account and re-raised, so the UI
    can say "reconnect" instead of silently showing stale numbers as fresh.
    """
    record = accounts.get_account(account_id)
    if record is None:
        raise ValueError("That account is no longer connected.")
    now = now or time.time()
    token = accounts.access_token(account_id)
    if adapter is None:
        adapter = adapter_for_analytics(record.platform)
    try:
        remote_posts = adapter.fetch_posts(token, limit=50)
    except PublishError as exc:
        accounts.mark_error(account_id, str(exc))
        raise
    new_posts = 0
    for remote in remote_posts:
        if not remote.platform_post_id:
            continue
        post_id, created = _upsert_remote(account_id, remote, now)
        new_posts += 1 if created else 0
        with accounts.db.connect() as conn:
            row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        post = _row_to_post(row)
        _capture_metrics(post_id, post, remote, now)
    labels = _refresh_labels(account_id, now)
    base = baseline(account_id, now)
    posts = list_posts(account_id, limit=500)
    total_views = sum(_num(p["metrics"].get("views")) for p in posts)
    followers = None
    profile: dict = {}
    if hasattr(adapter, "fetch_profile"):
        try:
            profile = adapter.fetch_profile(token) or {}
            followers = profile.get("followers")
        except Exception:  # noqa: BLE001 - profile data is optional
            profile = {}
    with accounts.db.connect() as conn:
        conn.execute(
            "INSERT INTO account_snapshots (account_id, captured_at, followers, total_views, payload) VALUES (?,?,?,?,?)",
            (account_id, now, followers, total_views, json.dumps({
                "posts": len(posts), "labels": labels, "baseline": base,
                "profile": profile, "platform": record.platform,
            })),
        )
    accounts.mark_synced(account_id, now)
    return {
        "account_id": account_id,
        "platform": record.platform,
        "synced_at": now,
        "remote_posts": len(remote_posts),
        "new_posts": new_posts,
        "total_posts": len(posts),
        "total_views": total_views,
        "followers": followers,
        "labels": labels,
        "baseline": base,
    }


def adapter_for_analytics(platform: str):
    if platform == "youtube":
        from .publish.youtube import YouTubeAdapter

        return YouTubeAdapter()
    if platform == "x":
        from .publish.x import XAdapter

        return XAdapter()
    raise PublishError(
        f"{limits_for(platform).label} analytics is not enabled yet. "
        "Connect YouTube or X for the personal loop today; TikTok and Instagram "
        "need approved developer apps first.",
        code="analytics_unavailable",
    )


def training_rows(account_id: str = "") -> list[dict]:
    """Full-feature app posts with a settled label, oldest first."""
    where = "AND p.account_id=?" if account_id else ""
    params: tuple[Any, ...] = (account_id,) if account_id else ()
    with accounts.db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT p.*, m.composite AS m_composite, m.label AS m_label, m.views AS m_views,
                   m.likes AS m_likes, m.comments AS m_comments, m.shares AS m_shares,
                   m.saves AS m_saves, m.age_hours AS m_age_hours
            FROM posts p
            JOIN post_metrics m ON m.id = (
                SELECT id FROM post_metrics WHERE post_id=p.id ORDER BY captured_at DESC, id DESC LIMIT 1
            )
            WHERE p.feature_coverage='full' AND p.origin='app' AND m.label IS NOT NULL
            {where}
            ORDER BY p.published_at ASC
            """,
            params,
        ).fetchall()
    out = []
    for row in rows:
        features = _parse_json(row["features"], {})
        if not features:
            continue
        out.append({
            "post_id": row["id"],
            "clip_id": row["clip_id"],
            "source_id": row["source_id"],
            "published_at": row["published_at"],
            "features": features,
            "label": int(row["m_label"]),
            "composite": float(row["m_composite"] or 0),
            "engagement_rate": engagement_rate({
                "views": row["m_views"], "likes": row["m_likes"],
                "comments": row["m_comments"], "shares": row["m_shares"], "saves": row["m_saves"],
            }),
            "metrics": {
                "views": row["m_views"], "likes": row["m_likes"],
                "comments": row["m_comments"], "shares": row["m_shares"],
                "saves": row["m_saves"], "age_hours": row["m_age_hours"],
            },
        })
    return out


def account_overview(account_id: str) -> dict:
    posts = list_posts(account_id, limit=200)
    now = time.time()
    eligible = [p for p in posts if _eligible(p, now)]
    return {
        "posts": posts[:50],
        "post_count": len(posts),
        "eligible_posts": len(eligible),
        "baseline": baseline(account_id, now),
        "labels_ready": len(eligible) >= MIN_POSTS_FOR_LABELS,
        "latest": eligible[0] if eligible else None,
    }
