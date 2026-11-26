"""Personal performance model: learns which clip features earn engagement.

This is deliberately separate from the approval re-ranker. The approval model
learns taste before publishing; this one learns what actually worked after a
post has had time to settle. It is only promoted when it beats a reach-only
baseline on a held-out slice and survives a permutation test.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import numpy as np

from . import analytics, db
from .config import SETTINGS
from .domain import ClipCandidate
from .learn.features import COLUMNS, to_vector, vector_from_stored
from .learn.ranker import RankerModel, _fit, auc_score

MIN_POSTS = 30
MIN_PER_CLASS = 10
MIN_AUC_GAIN = 0.03
PERMUTATIONS = 200
BLEND_CAP = 0.20


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _version(rows: list[dict], account_id: str) -> str:
    payload = [
        (row["post_id"], row["label"], row["features"], row.get("published_at", 0))
        for row in rows
    ]
    digest = hashlib.sha1(
        json.dumps({"account": account_id, "rows": payload}, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    return f"pm_{digest}"


def _split(X: np.ndarray, y: np.ndarray, views: np.ndarray):
    n = len(y)
    split = max(1, int(n * 0.75))
    split = min(split, n - 1)
    X_train, y_train = X[:split], y[:split]
    X_test, y_test = X[split:], y[split:]
    views_test = views[split:]
    if len(np.unique(y_test)) < 2:
        # Time-ordered tail had one class. Keep the split deterministic but
        # stratify by label so the held-out estimate is meaningful.
        pos = np.where(y == 1)[0]
        neg = np.where(y == 0)[0]
        test_idx = np.concatenate([
            pos[: max(1, len(pos) // 4)],
            neg[: max(1, len(neg) // 4)],
        ])
        train_idx = np.setdiff1d(np.arange(n), test_idx)
        X_train, y_train = X[train_idx], y[train_idx]
        X_test, y_test = X[test_idx], y[test_idx]
        views_test = views[test_idx]
    return X_train, y_train, X_test, y_test, views_test


def _permutation_p(y_test: np.ndarray, scores: np.ndarray, observed: float) -> float:
    rng = np.random.default_rng(42)
    hits = 0
    for _ in range(PERMUTATIONS):
        shuffled = rng.permutation(y_test)
        if auc_score(shuffled, scores) >= observed:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def train(account_id: str = "", *, now: float | None = None) -> dict:
    now = now or time.time()
    rows = analytics.training_rows(account_id)
    n = len(rows)
    positives = sum(1 for row in rows if row["label"] == 1)
    negatives = n - positives
    if n < MIN_POSTS:
        return {
            "promoted": False,
            "reason": f"needs {MIN_POSTS - n} more settled, full-feature posts",
            "n": n, "positives": positives, "negatives": negatives,
            "min_posts": MIN_POSTS,
        }
    if positives < MIN_PER_CLASS or negatives < MIN_PER_CLASS:
        return {
            "promoted": False,
            "reason": f"needs at least {MIN_PER_CLASS} wins and {MIN_PER_CLASS} misses",
            "n": n, "positives": positives, "negatives": negatives,
        }

    X = np.stack([
        vector_from_stored(row["features"], row.get("signals", {}), row.get("llm"))
        for row in rows
    ])
    y = np.array([row["label"] for row in rows], dtype=np.float32)
    views = np.array([float(row["metrics"].get("views", 0) or 0) for row in rows], dtype=np.float32)
    X_train, y_train, X_test, y_test, views_test = _split(X, y, views)
    if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
        return {"promoted": False, "reason": "not enough label variety", "n": n}

    model = _fit(X_train, y_train, SETTINGS.learn)
    scores = model.predict_matrix(X_test)
    model_auc = auc_score(y_test, scores)
    baseline_auc = auc_score(y_test, views_test)
    p_value = _permutation_p(y_test, scores, model_auc)
    model.auc = round(model_auc, 4)
    gain = model_auc - baseline_auc
    promoted = gain >= MIN_AUC_GAIN and p_value < 0.05
    version = _version(rows, account_id)
    metrics = {
        "promoted": promoted,
        "n": n, "positives": positives, "negatives": negatives,
        "auc": round(model_auc, 4), "baseline_auc": round(baseline_auc, 4),
        "gain": round(gain, 4), "p_value": round(p_value, 4),
        "min_posts": MIN_POSTS, "min_per_class": MIN_PER_CLASS,
        "min_auc_gain": MIN_AUC_GAIN,
        "blend_cap": BLEND_CAP,
        "trained_at": now,
        "account_id": account_id,
    }
    payload = model.to_dict()
    payload.update({
        "version": version,
        "feature_importance": {
            name: round(float(weight), 6) for name, weight in zip(COLUMNS, model.weights)
        },
        "account_id": account_id,
    })
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO personal_models (version, created_at, payload, metrics, active, data_window)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(version) DO UPDATE SET
                payload=excluded.payload, metrics=excluded.metrics,
                created_at=excluded.created_at
            """,
            (version, now, json.dumps(payload), json.dumps(metrics), 0, account_id or "all"),
        )
        if promoted:
            conn.execute("UPDATE personal_models SET active=0")
            conn.execute("UPDATE personal_models SET active=1 WHERE version=?", (version,))
    result = {
        "promoted": promoted,
        "version": version,
        "reason": (
            f"held-out AUC {model_auc:.3f} beats reach baseline {baseline_auc:.3f} "
            f"(p={p_value:.3f})"
            if promoted else
            f"not promoted: AUC {model_auc:.3f} vs reach {baseline_auc:.3f}, p={p_value:.3f}"
        ),
        **metrics,
        "feature_importance": payload["feature_importance"],
    }
    return result


def active_record() -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM personal_models WHERE active=1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return _row_to_state(row) if row is not None else None


def active() -> RankerModel | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT payload, metrics FROM personal_models WHERE active=1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    payload = _loads(row["payload"], {})
    model = RankerModel.from_dict(payload)
    if model is not None:
        metrics = _loads(row["metrics"], {})
        model.auc = float(metrics.get("auc", model.auc))
    return model


def activate(version: str) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM personal_models WHERE version=?", (version,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown personal model: {version}")
        metrics = _loads(row["metrics"], {})
        promoted = bool(metrics["promoted"]) if "promoted" in metrics else (
            float(metrics.get("gain", 0)) >= MIN_AUC_GAIN and float(metrics.get("p_value", 1)) < 0.05
        )
        if not promoted:
            raise ValueError("That model did not clear the promotion gate; it cannot be activated manually.")
        conn.execute("UPDATE personal_models SET active=0")
        conn.execute("UPDATE personal_models SET active=1 WHERE version=?", (version,))
        row = conn.execute("SELECT * FROM personal_models WHERE version=?", (version,)).fetchone()
    return _row_to_state(row)


def rollback() -> dict | None:
    """Return to the approval-only ranker, keeping the artifact for inspection."""
    with db.connect() as conn:
        conn.execute("UPDATE personal_models SET active=0")
    return None


def _row_to_state(row) -> dict:
    payload = _loads(row["payload"], {})
    return {
        "version": row["version"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "data_window": row["data_window"],
        "metrics": _loads(row["metrics"], {}),
        "feature_importance": payload.get("feature_importance", {}),
    }


def history(limit: int = 20) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM personal_models ORDER BY created_at DESC LIMIT ?", (max(1, limit),)
        ).fetchall()
    return [_row_to_state(row) for row in rows]


def state(account_id: str = "") -> dict:
    rows = analytics.training_rows(account_id)
    positives = sum(1 for row in rows if row["label"] == 1)
    active_row = active_record()
    return {
        "ready": len(rows) >= MIN_POSTS and positives >= MIN_PER_CLASS and (len(rows) - positives) >= MIN_PER_CLASS,
        "posts": len(rows),
        "positives": positives,
        "negatives": len(rows) - positives,
        "min_posts": MIN_POSTS,
        "min_per_class": MIN_PER_CLASS,
        "min_auc_gain": MIN_AUC_GAIN,
        "blend_cap": BLEND_CAP,
        "active": active_row,
        "history": history(10),
    }


def apply_blend(
    candidates: list[ClipCandidate],
    model: RankerModel | None,
    taste_model: RankerModel | None,
    personal_weight: float = BLEND_CAP,
    taste_weight: float = 0.35,
) -> None:
    """Blend both learned scores into the base final score, respecting the cap.

    Applying each learner sequentially would multiply their weights. This applies
    both to the same base score so the documented weights stay literal.
    """
    if model is None or not model.weights or not candidates:
        return
    personal_weight = max(0.0, min(BLEND_CAP, float(personal_weight)))
    taste_weight = max(0.0, float(taste_weight))
    if personal_weight + taste_weight > 0.55:
        scale = 0.55 / (personal_weight + taste_weight)
        personal_weight *= scale
        taste_weight *= scale
    X = np.stack([to_vector(candidate) for candidate in candidates])
    personal_scores = model.predict_matrix(X)
    taste_scores = taste_model.predict_matrix(X) if taste_model else None
    for index, candidate in enumerate(candidates):
        base = float(candidate.final)
        personal = float(personal_scores[index])
        if taste_scores is None:
            blended = base * (1 - personal_weight) + personal * personal_weight
        else:
            blended = (
                base * (1 - personal_weight - taste_weight)
                + personal * personal_weight
                + float(taste_scores[index]) * taste_weight
            )
        candidate.final = round(blended, 4)
