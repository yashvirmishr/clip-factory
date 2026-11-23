"""Few-shot exemplar memory.

The cheapest way to make a local model write better hooks is not to train it -
it is to show it three windows you approved and three you rejected, chosen
because they resemble the one it is judging.

Retrieval uses the hashed lexical vectors from ``textvec``: instant, offline,
no embedding model resident in RAM.
"""

from __future__ import annotations

import numpy as np

from ..textvec import cosine, vector
from .features import label_of


def retrieve_exemplars(
    text: str, decisions: list[dict], k: int = 3
) -> list[dict]:
    if not decisions or k <= 0:
        return []
    query = vector(text)
    approved: list[tuple[float, dict]] = []
    rejected: list[tuple[float, dict]] = []
    for row in decisions:
        label = label_of(row.get("action", ""))
        if label is None or not row.get("text"):
            continue
        similarity = cosine(query, vector(row["text"]))
        entry = {
            "action": "approve" if label == 1 else "reject",
            "score": row.get("llm_score"),
            "reason": row.get("reason", ""),
            "hook": row.get("hook", ""),
            "text": row.get("text", ""),
            "similarity": round(similarity, 3),
        }
        (approved if label == 1 else rejected).append((similarity, entry))

    def take(pool: list[tuple[float, dict]]) -> list[dict]:
        pool.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in pool[:k]]

    return take(approved) + take(rejected)


def similarity_floor(decisions: list[dict], floor: float = 0.15) -> list[dict]:
    """Drop exemplars that are lexically unrelated - noise in the prompt is worse
    than an empty example section."""
    return [d for d in decisions if d.get("similarity", 0.0) >= floor]


def exemplar_count(decisions: list[dict]) -> dict[str, int]:
    approvals = sum(1 for d in decisions if label_of(d.get("action", "")) == 1)
    rejections = sum(1 for d in decisions if label_of(d.get("action", "")) == 0)
    return {"approve": approvals, "reject": rejections}


def mean_similarity(decisions: list[dict]) -> float:
    if not decisions:
        return 0.0
    return float(np.mean([d.get("similarity", 0.0) for d in decisions]))
