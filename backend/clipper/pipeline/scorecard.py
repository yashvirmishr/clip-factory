"""The visible scorecard: what "is this clip garbage" means, per clip.

Borrowed from the ShortsFlow benchmark shape (sentence-bounded edges, hook
present, grounded title, right length) so quality is a number on screen rather
than a vibe in a changelog.
"""

from __future__ import annotations

import re

from ..domain import ClipCandidate, ScoreItem, WindowFeatures
from ..textvec import SECOND_PERSON, tokenize
from .gates import hook_cue

_NUM_RE = re.compile(r"\d+")
_STOP = frozenset(
    "the a an of to and or but is are was were be been it its this that these those "
    "i you he she they we me my your his her their them in on at for with from as".split()
)


def grounding_ratio(hook: str, text: str) -> float:
    """Fraction of the hook's content words that actually occur in the clip."""
    hook_tokens = [t for t in tokenize(hook) if t not in _STOP]
    if not hook_tokens:
        return 1.0
    clip_tokens = set(tokenize(text))
    hits = sum(1 for t in hook_tokens if t in clip_tokens)
    ratio = hits / len(hook_tokens)
    hook_numbers = set(_NUM_RE.findall(hook))
    if hook_numbers and not hook_numbers.issubset(set(_NUM_RE.findall(text))):
        ratio = min(ratio, 0.4)
    return ratio


def build_scorecard(
    candidate: ClipCandidate, features: WindowFeatures, grounded_ratio: float
) -> list[ScoreItem]:
    gate_ids = {g.id: g for g in candidate.gates}

    def gate(item_id: str) -> ScoreItem:
        result = gate_ids.get(item_id)
        return ScoreItem(
            id=item_id,
            label=(result.label if result else "") or item_id.replace("_", " "),
            passed=bool(result.passed) if result else True,
            detail=result.detail if result else "",
        )

    hook_text = candidate.llm.hook if candidate.llm else ""
    return [
        ScoreItem(id="sentence_start", label="Opens on a sentence", passed=True),
        gate("ends_sentence"),
        gate("hook_in_first_seconds"),
        ScoreItem(
            id="hook_grounded",
            label="Hook is grounded",
            passed=grounded_ratio >= 0.7,
            detail=f"{grounded_ratio:.0%} of hook words appear in the clip",
        ),
        gate("duration_range"),
        gate("stands_alone"),
        gate("asr_confidence"),
        ScoreItem(
            id="hook_readable",
            label="Hook is readable",
            passed=0 < len(hook_text.split()) <= 12,
            detail=f"{len(hook_text.split())} words",
        ),
    ]


def reel_quality(candidates: list[ClipCandidate]) -> float:
    scored = [c for c in candidates if c.rank is not None]
    if not scored:
        return 0.0
    return round(sum(c.scorecard_ratio() for c in scored) / len(scored), 4)


def describe_signals(text: str) -> str:
    """Human-readable 'why this ranked here' line for the inspector."""
    bits: list[str] = []
    cue = hook_cue(text)
    if cue:
        bits.append(f"hook cue: {cue}")
    if any(t in SECOND_PERSON for t in tokenize(text)):
        bits.append("speaks to the viewer")
    return ", ".join(bits)
