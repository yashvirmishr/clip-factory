"""Deterministic moment signals.

The LLM is a re-ranker, never the detector. These five signals do the
detection, and they cost one pass over arrays we already computed:

    audio        loudness percentile inside the window
    excitement   spectral-flux bursts (a *proxy*, not laughter detection)
    chat         Twitch message rate (absent for files - weight is then
                 redistributed rather than zeroed, which matters: a missing
                 signal must not silently penalise every window)
    speech       words per second, gated by speech coverage
    hook_lexicon hook-word density in the opening line
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ..config import SignalWeights
from ..domain import Utterance, WindowFeatures
from ..textvec import (
    PROFANITY,
    SECOND_PERSON,
    caps_ratio,
    count_tokens,
    hook_lexicon_hits,
)
from .media import AudioAnalysis

LOW_CONF_THRESHOLD = 0.45
# Chat is only a signal when there is enough of it to form a rate. Two messages
# in a two-hour VOD are timestamps, not a crowd; min/max normalisation would turn
# those two points into the strongest moments in the stream.
MIN_CHAT_RATE = 0.002


def load_chat_rate(path: str | Path | None, duration: float) -> np.ndarray | None:
    """chat-downloader style JSON (``[{"content_offset_seconds": 12.3}, ...]``)."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(payload, dict):
        payload = payload.get("comments", [])
    if not isinstance(payload, list):
        return None
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    buckets = np.zeros(int(max(1.0, seconds)) + 1, dtype=np.float32)
    kept = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        value = item.get("content_offset_seconds", item.get("offset"))
        if value is None:
            continue
        try:
            t = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(t) or t < 0:
            continue
        idx = int(t)
        if 0 <= idx < buckets.size:
            buckets[idx] += 1.0
            kept += 1
    # A parseable file with no usable timestamps is not a signal. Returning a
    # zero array would mark chat as available, give every window the same 0.5
    # rank, and quietly add that constant to the fused score. The same applies
    # to a file that is technically valid but far too sparse to be a rate.
    if kept < seconds * MIN_CHAT_RATE:
        return None
    return buckets


def window_features(
    text: str,
    start: float,
    end: float,
    words_probs: list[float],
    analysis: AudioAnalysis | None,
) -> WindowFeatures:
    duration = max(0.001, end - start)
    tokens = text.split()
    word_count = len(tokens)
    probs = np.array(words_probs, dtype=np.float32) if words_probs else np.array([1.0])
    low_conf = float(np.mean(probs < LOW_CONF_THRESHOLD)) if probs.size else 0.0
    coverage = analysis.coverage(start, end) if analysis is not None else 1.0
    return WindowFeatures(
        duration=round(duration, 3),
        word_count=word_count,
        words_per_sec=round(word_count / duration, 3),
        question_count=text.count("?"),
        exclaim_count=text.count("!"),
        second_person=count_tokens(text, SECOND_PERSON),
        number_count=sum(1 for t in tokens if any(c.isdigit() for c in t)),
        hook_lexicon_hits=hook_lexicon_hits(text),
        profanity=count_tokens(text, PROFANITY),
        caps_ratio=round(caps_ratio(text), 4),
        mean_word_prob=round(float(probs.mean()), 4),
        low_conf_ratio=round(low_conf, 4),
        speech_coverage=round(coverage, 4),
        start_in_stream=round(start, 3),
        end_in_stream=round(end, 3),
    )


def raw_signals(
    features: WindowFeatures,
    analysis: AudioAnalysis | None,
    chat: np.ndarray | None,
) -> dict[str, float]:
    start, end = features.start_in_stream, features.end_in_stream
    audio = 0.0
    excitement = 0.0
    if analysis is not None and analysis.rms.size:
        audio = analysis.bucket(start, end, analysis.rms)
        excitement = analysis.bucket(start, end, analysis.flux) * (
            0.5 + analysis.bucket(start, end, analysis.zcr)
        )
    chat_rate = 0.0
    if chat is not None and chat.size:
        lo, hi = int(max(0, start)), int(min(chat.size, max(start + 1, end)))
        if hi > lo:
            chat_rate = float(chat[lo:hi].mean())

    wps = features.words_per_sec
    speech = min(1.0, wps / 4.5) * min(1.0, features.speech_coverage / 0.6)
    hook = min(1.0, features.hook_lexicon_hits / max(1.0, features.word_count / 60.0))

    return {
        "audio": audio,
        "excitement": excitement,
        "chat": chat_rate,
        "speech": speech,
        "hook_lexicon": hook,
    }


def percentile_rank(values: np.ndarray) -> np.ndarray:
    """Rank-based normalisation to [0, 1]. Robust to outliers by construction."""
    if values.size == 0:
        return values
    if values.size == 1:
        return np.array([0.5], dtype=np.float32)
    if float(values.max() - values.min()) < 1e-9:
        return np.full(values.shape, 0.5, dtype=np.float32)
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float32)
    ranks[order] = np.arange(values.size, dtype=np.float32)
    return ranks / (values.size - 1)


SIGNAL_KEYS = ("audio", "excitement", "chat", "speech", "hook_lexicon")


def normalise_signals(
    raw: dict[str, list[float]], available: set[str]
) -> list[dict[str, float]]:
    """Per-signal percentile ranks across all candidate windows."""
    count = len(next(iter(raw.values()))) if raw else 0
    if count == 0:
        return []
    ranked: dict[str, np.ndarray] = {}
    for key in SIGNAL_KEYS:
        values = np.array(raw.get(key, [0.0] * count), dtype=np.float32)
        ranked[key] = percentile_rank(values)
    out: list[dict[str, float]] = []
    for i in range(count):
        out.append(
            {
                key: (round(float(ranked[key][i]), 4) if key in available else 0.0)
                for key in SIGNAL_KEYS
            }
        )
    return out


def fuse(
    signals: dict[str, float], weights: SignalWeights, available: set[str]
) -> float:
    configured = weights.normalised()
    total_weight = 0.0
    total = 0.0
    for key in SIGNAL_KEYS:
        if key not in available:
            continue
        weight = configured[key]
        total += weight * signals.get(key, 0.0)
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return round(total / total_weight, 4)


def blend_with_llm(fused: float, llm_score: int | None, signal_weight: float, llm_weight: float) -> float:
    if llm_score is None:
        return fused
    llm_normalised = max(0, min(100, llm_score)) / 100.0
    return round(
        fused * signal_weight + llm_normalised * llm_weight, 4
    )
