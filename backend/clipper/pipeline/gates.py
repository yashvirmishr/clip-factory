"""Quality gates: the anti-garbage layer.

G1 input gates reject windows the model should never have been asked about
(garbled transcript, hallucinated text, sponsor reads, stream warm-up).
G2 structural gates reject windows that would make a bad clip even if the
moment is good (no hook, starts mid-thought, wrong length).
"""

from __future__ import annotations

import re

from ..config import GateConfig
from ..domain import GateResult, WindowFeatures, Word
from ..textvec import (
    HOOK_WORDS,
    PROFANITY,
    SECOND_PERSON,
    starts_with_deictic,
)
from .windows import Window

_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_LATIN_RE = re.compile(r"[A-Za-z]")

HOOK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("question", r"\?"),
    ("number", r"\b\d+\b"),
    ("second_person", r"\b(you|your|you're|youre)\b"),
    ("why_how_what", r"\b(why|how|what)\b"),
    ("superlative", r"\b(worst|best|ever|never|always|nobody|everyone)\b"),
)


def non_latin_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    cjk = len(_CJK_RE.findall(text))
    return cjk / max(1, len(letters))


def hook_cue(text: str) -> str | None:
    lowered = text.lower()
    for label, pattern in HOOK_PATTERNS:
        if re.search(pattern, lowered):
            return label
    if any(tok.strip(".,!?") in HOOK_WORDS for tok in lowered.split()):
        return "hook_word"
    if any(tok.strip(".,!?").upper() == tok.strip(".,!?") and len(tok) > 3 for tok in text.split()):
        return "caps"
    if any(tok.strip(".,!?").lower() in PROFANITY for tok in lowered.split()):
        return "profanity"
    return None


def opening_hook(words: list[Word], window_start: float, window_s: float) -> str | None:
    opening = [w.text for w in words if w.start < window_start + window_s]
    if not opening:
        opening = [w.text for w in words[:12]]
    return hook_cue(" ".join(opening))


def evaluate_gates(
    window: Window,
    features: WindowFeatures,
    words: list[Word],
    cfg: GateConfig,
    stream_duration: float,
) -> list[GateResult]:
    results: list[GateResult] = []

    def add(gid: str, passed: bool, detail: str = "", severity: str = "block") -> None:
        results.append(GateResult(id=gid, passed=passed, severity=severity, detail=detail))

    # ---- G1: input gates -------------------------------------------------
    confident = (
        features.mean_word_prob >= cfg.min_asr_confidence
        and features.low_conf_ratio <= cfg.max_low_conf_ratio
    )
    add(
        "asr_confidence",
        confident,
        f"conf {features.mean_word_prob:.2f}, low {features.low_conf_ratio:.0%}",
    )

    add(
        "speech_coverage",
        features.speech_coverage >= cfg.min_speech_coverage,
        f"speech {features.speech_coverage:.0%}",
    )

    hallucination = non_latin_ratio(window.text)
    add(
        "not_hallucinated",
        hallucination <= cfg.max_non_latin_ratio,
        f"non-latin {hallucination:.0%}",
    )

    sponsor = next(
        (kw for kw in cfg.sponsor_keywords if kw in window.text.lower()), ""
    )
    add("not_sponsor", not sponsor, f"matched '{sponsor}'" if sponsor else "")

    warmup_ok = stream_duration <= cfg.stream_warmup_s * 2 or window.start >= cfg.stream_warmup_s
    add("past_warmup", warmup_ok, f"starts at {window.start:.0f}s")

    add("min_words", features.word_count >= cfg.min_words, f"{features.word_count} words")

    blocked = next((term for term in cfg.blocklist if term.lower() in window.text.lower()), "")
    add("not_blocked", not blocked, f"blocked '{blocked}'" if blocked else "")

    # ---- G2: structural gates -------------------------------------------
    add(
        "duration_range",
        cfg.duration_min_s <= window.duration <= cfg.duration_max_s,
        f"{window.duration:.1f}s",
    )

    opening_cue = opening_hook(words, window.start, cfg.hook_window_s)
    add("hook_in_first_seconds", opening_cue is not None, opening_cue or "no hook cue")

    deictic = starts_with_deictic(window.text)
    add("stands_alone", deictic is None, f"opens with '{deictic}'" if deictic else "")

    add("ends_sentence", window.last_terminal, "ends mid-sentence" if not window.last_terminal else "")

    return results
