"""Feature vector for the personal re-ranker.

One fixed column order shared by training and inference. Everything is scaled
to roughly 0..1 so a plain logistic regression converges without a scaler.
"""

from __future__ import annotations

import numpy as np

from ..domain import ClipCandidate, WindowFeatures

COLUMNS: tuple[str, ...] = (
    "audio",
    "excitement",
    "chat",
    "speech",
    "hook_lexicon",
    "llm_score",
    "has_llm",
    "standalone",
    "payoff",
    "duration",
    "words_per_sec",
    "questions",
    "second_person",
    "numbers",
    "hook_hits",
    "profanity",
    "asr_conf",
    "low_conf",
    "coverage",
    "position",
    "word_count",
    "caps",
)


def _norm(value: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return float(min(1.0, max(0.0, value / scale)))


def named_features(candidate: ClipCandidate) -> dict[str, float]:
    f: WindowFeatures = candidate.features or WindowFeatures()
    llm = candidate.llm
    signals = candidate.signals or {}
    return {
        "audio": signals.get("audio", 0.0),
        "excitement": signals.get("excitement", 0.0),
        "chat": signals.get("chat", 0.0),
        "speech": signals.get("speech", 0.0),
        "hook_lexicon": signals.get("hook_lexicon", 0.0),
        "llm_score": (llm.score / 100.0) if llm else 0.0,
        "has_llm": 1.0 if llm else 0.0,
        "standalone": 1.0 if (llm and llm.understands_standalone) else 0.0,
        "payoff": 1.0 if (llm and llm.has_payoff) else 0.0,
        "duration": _norm(f.duration, 90.0),
        "words_per_sec": _norm(f.words_per_sec, 5.0),
        "questions": _norm(f.question_count, 3),
        "second_person": _norm(f.second_person, 5),
        "numbers": _norm(f.number_count, 3),
        "hook_hits": _norm(f.hook_lexicon_hits, 5),
        "profanity": _norm(f.profanity, 3),
        "asr_conf": float(f.mean_word_prob),
        "low_conf": float(f.low_conf_ratio),
        "coverage": float(f.speech_coverage),
        "position": _norm(f.start_in_stream, 3600.0),
        "word_count": _norm(f.word_count, 200.0),
        "caps": _norm(f.caps_ratio, 0.3),
    }


def to_vector(candidate: ClipCandidate) -> np.ndarray:
    named = named_features(candidate)
    return np.array([named[c] for c in COLUMNS], dtype=np.float32)


def vector_from_stored(features: dict, signals: dict, llm: dict | None = None) -> np.ndarray:
    """Rebuild the vector from a decision log row (training path)."""
    from ..domain import LLMJudgement

    f = WindowFeatures.model_validate(features) if features else WindowFeatures()
    judgement = LLMJudgement.model_validate(llm) if llm else None
    stub = ClipCandidate(
        id="stored",
        source_id="stored",
        start=f.start_in_stream,
        end=f.end_in_stream,
        text="",
        signals=signals or {},
        features=f,
        llm=judgement,
    )
    return to_vector(stub)


def label_of(action: str) -> int | None:
    if action in ("approve", "export", "send_to_editor"):
        return 1
    if action == "reject":
        return 0
    return None
