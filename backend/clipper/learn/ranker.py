"""The personal re-ranker: a tiny logistic model over the decision log.

Why not fine-tune: at a few hundred examples a 7B LoRA overfits and few-shot
prompting usually wins. This costs milliseconds on the CPU, uses no extra RAM,
and learns the one thing a general model cannot - *your* thresholds.

Promotion is gated: a new ranker only replaces the live one if it beats both the
pipeline score and the previous ranker on a time-based holdout. That gate is
what stops the learning loop from degrading into garbage over time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..config import LearnConfig
from ..domain import ClipCandidate
from .features import COLUMNS, label_of, vector_from_stored

PROMOTION_MARGIN = 0.02


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))


def auc_score(labels: np.ndarray, scores: np.ndarray) -> float:
    """Rank-based AUC; returns 0.5 when a class is missing."""
    positives = int(labels.sum())
    negatives = int(len(labels) - positives)
    if positives == 0 or negatives == 0:
        return 0.5
    order = np.argsort(scores, kind="stable")
    ranks = np.empty(len(scores), dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1)
    return float((ranks[labels == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


@dataclass
class RankerModel:
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    mean: list[float] = field(default_factory=list)
    std: list[float] = field(default_factory=list)
    n: int = 0
    auc: float = 0.5
    created_at: float = 0.0

    def predict_matrix(self, X: np.ndarray) -> np.ndarray:
        w = np.array(self.weights, dtype=np.float32)
        mean = np.array(self.mean, dtype=np.float32)
        std = np.array(self.std, dtype=np.float32)
        if w.size != X.shape[1] or mean.size != X.shape[1]:
            return np.full(X.shape[0], 0.5, dtype=np.float32)
        Z = (X - mean) / np.where(std < 1e-6, 1.0, std)
        return _sigmoid(Z @ w + self.bias)

    def to_dict(self) -> dict:
        return {
            "columns": list(COLUMNS),
            "weights": self.weights,
            "bias": self.bias,
            "mean": self.mean,
            "std": self.std,
            "n": self.n,
            "auc": self.auc,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "RankerModel | None":
        if not payload or payload.get("columns") != list(COLUMNS):
            return None
        return cls(
            weights=payload.get("weights", []),
            bias=payload.get("bias", 0.0),
            mean=payload.get("mean", []),
            std=payload.get("std", []),
            n=int(payload.get("n", 0)),
            auc=float(payload.get("auc", 0.5)),
            created_at=float(payload.get("created_at", 0.0)),
        )


@dataclass
class TrainOutcome:
    promoted: bool
    reason: str
    model: RankerModel | None = None
    auc: float = 0.5
    baseline_auc: float = 0.5
    n: int = 0


def _fit(X: np.ndarray, y: np.ndarray, cfg: LearnConfig) -> RankerModel:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    Z = (X - mean) / np.where(std < 1e-6, 1.0, std)
    w = np.zeros(Z.shape[1], dtype=np.float32)
    b = 0.0
    n = Z.shape[0]
    for _ in range(cfg.epochs):
        p = _sigmoid(Z @ w + b)
        grad = (p - y)
        w -= cfg.lr * (Z.T @ grad / n + cfg.l2 * w)
        b -= cfg.lr * float(grad.mean())
    return RankerModel(
        weights=[round(float(v), 6) for v in w],
        bias=round(float(b), 6),
        mean=[round(float(v), 6) for v in mean],
        std=[round(float(v), 6) for v in std],
        n=int(n),
        created_at=time.time(),
    )


def build_dataset(decisions: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Time-ordered (X, y, baseline_scores). Oldest first."""
    rows = sorted(decisions, key=lambda d: d.get("created_at", 0.0))
    X, y, baseline = [], [], []
    for row in rows:
        label = label_of(row.get("action", ""))
        if label is None:
            continue
        X.append(
            vector_from_stored(
                row.get("features", {}), row.get("signals", {}), row.get("llm", {})
            )
        )
        y.append(label)
        baseline.append(float(row.get("final", 0.0)))
    if not X:
        return np.zeros((0, len(COLUMNS)), dtype=np.float32), np.zeros(0), np.zeros(0)
    return (
        np.stack(X),
        np.array(y, dtype=np.float32),
        np.array(baseline, dtype=np.float32),
    )


def train_from_decisions(
    decisions: list[dict], cfg: LearnConfig, current: RankerModel | None = None
) -> TrainOutcome:
    X, y, baseline = build_dataset(decisions)
    n = int(y.size)
    if n < cfg.min_decisions_for_ranker:
        return TrainOutcome(
            promoted=False,
            reason=f"needs {cfg.min_decisions_for_ranker - n} more decisions",
            n=n,
        )
    if len(np.unique(y)) < 2:
        return TrainOutcome(promoted=False, reason="need both approvals and rejections", n=n)

    split = max(1, int(n * (1 - cfg.holdout_ratio)))
    split = min(split, n - 1)
    X_train, y_train = X[:split], y[:split]
    X_test, y_test = X[split:], y[split:]
    base_test = baseline[split:]

    if len(np.unique(y_test)) < 2:
        # Holdout has one class: fall back to a 5-fold-ish alternating split.
        mask = np.arange(n) % 5 == 0
        X_test, y_test = X[mask], y[mask]
        base_test = baseline[mask]
        X_train, y_train = X[~mask], y[~mask]
    if len(np.unique(y_test)) < 2:
        return TrainOutcome(promoted=False, reason="not enough label variety", n=n)

    model = _fit(X_train, y_train, cfg)
    test_scores = model.predict_matrix(X_test)
    model_auc = auc_score(y_test, test_scores)
    baseline_auc = auc_score(y_test, base_test)
    model.auc = round(model_auc, 4)

    best_auc = max(baseline_auc, current.auc if current else 0.0)
    if model_auc < best_auc + PROMOTION_MARGIN:
        return TrainOutcome(
            promoted=False,
            reason=f"no held-out gain (new {model_auc:.3f} vs best {best_auc:.3f})",
            model=model,
            auc=model_auc,
            baseline_auc=baseline_auc,
            n=n,
        )
    return TrainOutcome(
        promoted=True,
        reason=f"held-out AUC {model_auc:.3f} beats {best_auc:.3f}",
        model=model,
        auc=model_auc,
        baseline_auc=baseline_auc,
        n=n,
    )


def apply_ranker(
    candidates: list[ClipCandidate],
    model: RankerModel | None,
    weight: float = 0.6,
) -> None:
    """Blend the learned taste score into ``final`` in place.

    Blending rather than replacing keeps the signal/LLM score meaningful, so a
    ranker trained on 40 decisions cannot collapse ranking to a single feature.
    """
    if model is None or not model.weights or not candidates:
        return
    from .features import to_vector

    X = np.stack([to_vector(c) for c in candidates])
    learned = model.predict_matrix(X)
    for candidate, score in zip(candidates, learned):
        candidate.final = round(
            float(candidate.final) * (1 - weight) + float(score) * weight, 4
        )


def quality_stats(decisions: list[dict]) -> dict:
    approvals = sum(1 for d in decisions if label_of(d.get("action", "")) == 1)
    rejections = sum(1 for d in decisions if label_of(d.get("action", "")) == 0)
    reasons: dict[str, int] = {}
    for d in decisions:
        if d.get("action") == "reject" and d.get("reason"):
            reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
    total = approvals + rejections
    return {
        "decisions": len(decisions),
        "approvals": approvals,
        "rejections": rejections,
        "approval_rate": round(approvals / total, 4) if total else 0.0,
        "reject_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    }
