"""Final selection: greedy top-N with overlap and near-duplicate rejection.

Overlap and dedupe are *selection* concerns, not window concerns - a window is
not bad because a better one covered it, so these failures are recorded on the
candidate as warnings rather than blanket-blocking it.
"""

from __future__ import annotations

import numpy as np

from ..config import GateConfig
from ..domain import ClipCandidate, GateResult
from ..textvec import cosine, vector


def _overlap_ratio(a: ClipCandidate, b: ClipCandidate) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.duration, b.duration)
    return inter / shorter if shorter > 0 else 0.0


def select_clips(
    candidates: list[ClipCandidate],
    cfg: GateConfig,
    limit: int = 10,
) -> tuple[list[ClipCandidate], list[ClipCandidate]]:
    """Return (selected, dropped). Selected carry ``rank``; dropped carry a gate."""
    viable = [c for c in candidates if not c.blocked]
    viable.sort(key=lambda c: c.final, reverse=True)

    vectors = {c.id: vector(c.text) for c in viable}
    selected: list[ClipCandidate] = []
    dropped: list[ClipCandidate] = []

    for candidate in viable:
        if len(selected) >= limit:
            dropped.append(
                candidate.model_copy(
                    update={
                        "blocked": True,
                        "gates": candidate.gates
                        + [GateResult(id="beyond_limit", passed=False, severity="warn", detail="rank below cut")],
                    }
                )
            )
            continue

        conflict = next(
            (s for s in selected if _overlap_ratio(candidate, s) > cfg.max_overlap_ratio),
            None,
        )
        if conflict is not None:
            dropped.append(
                candidate.model_copy(
                    update={
                        "blocked": True,
                        "gates": candidate.gates
                        + [
                            GateResult(
                                id="no_overlap",
                                passed=False,
                                severity="warn",
                                detail=f"overlaps rank {conflict.rank}",
                            )
                        ],
                    }
                )
            )
            continue

        duplicate = next(
            (
                s
                for s in selected
                if cosine(vectors[candidate.id], vectors[s.id]) >= cfg.dedupe_cosine
            ),
            None,
        )
        if duplicate is not None:
            dropped.append(
                candidate.model_copy(
                    update={
                        "blocked": True,
                        "gates": candidate.gates
                        + [
                            GateResult(
                                id="not_duplicate",
                                passed=False,
                                severity="warn",
                                detail=f"near-duplicate of rank {duplicate.rank}",
                            )
                        ],
                    }
                )
            )
            continue

        selected.append(
            candidate.model_copy(
                update={
                    "rank": len(selected) + 1,
                    "gates": candidate.gates
                    + [GateResult(id="no_overlap", passed=True), GateResult(id="not_duplicate", passed=True)],
                }
            )
        )

    return selected, dropped


def diversify_order(candidates: list[ClipCandidate], window_s: float = 1800.0, max_per_window: int = 2) -> list[ClipCandidate]:
    """Cap how many clips come from the same half-hour region.

    A four-hour stream has dead regions; without this the top ten clips are
    frequently all from the same hot streak.
    """
    buckets: dict[int, int] = {}
    out: list[ClipCandidate] = []
    overflow: list[ClipCandidate] = []
    for candidate in sorted(candidates, key=lambda c: c.final, reverse=True):
        bucket = int(candidate.start // window_s)
        if buckets.get(bucket, 0) >= max_per_window:
            overflow.append(candidate)
            continue
        buckets[bucket] = buckets.get(bucket, 0) + 1
        out.append(candidate)
    return out + overflow


def as_matrix(candidates: list[ClipCandidate]) -> np.ndarray:
    """Feature matrix for the learner (stable column order)."""
    from ..learn.features import to_vector

    return np.stack([to_vector(c) for c in candidates]) if candidates else np.zeros((0, 0))
