"""Candidate window construction.

Windows snap to utterance boundaries rather than a fixed grid, which is what
makes "starts and ends on a sentence" true by construction instead of a
post-hoc filter that throws work away.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import WindowConfig
from ..domain import Utterance


@dataclass
class Window:
    start: float
    end: float
    text: str
    word_probs: list[float] = field(default_factory=list)
    utterance_count: int = 0
    first_terminal: bool = True
    last_terminal: bool = True
    starts_with_deictic: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _join(utterances: list[Utterance]) -> tuple[str, list[float]]:
    text = " ".join(u.text.strip() for u in utterances).strip()
    probs = [w.prob for u in utterances for w in u.words]
    return text, probs


def build_windows(
    utterances: list[Utterance],
    cfg: WindowConfig,
    max_windows: int = 900,
) -> list[Window]:
    if not utterances:
        return []
    ordered = sorted(utterances, key=lambda u: u.start)
    windows: list[Window] = []
    n = len(ordered)

    for i in range(n):
        start = ordered[i].start
        accumulated: list[Utterance] = []
        emitted_short = False
        for j in range(i, n):
            candidate = ordered[j]
            span = candidate.end - start
            if span > cfg.max_s:
                break
            accumulated.append(candidate)
            if span < cfg.min_s:
                continue
            is_target = span >= cfg.target_s
            if is_target or not emitted_short:
                words = [w for u in accumulated for w in u.words]
                text, probs = _join(accumulated)
                windows.append(
                    Window(
                        start=round(start, 3),
                        end=round(candidate.end, 3),
                        text=text,
                        word_probs=probs,
                        utterance_count=len(accumulated),
                        first_terminal=True,
                        last_terminal=bool(candidate.terminal),
                        starts_with_deictic=False,
                    )
                )
                emitted_short = emitted_short or not is_target
            if is_target:
                break

    if not windows:
        return []

    windows = _dedupe(windows)
    windows.sort(key=lambda w: (w.start, w.end))
    if len(windows) > max_windows:
        stride = len(windows) / max_windows
        windows = [windows[int(k * stride)] for k in range(max_windows)]
    return windows


def _dedupe(windows: list[Window]) -> list[Window]:
    seen: set[tuple[float, float]] = set()
    out: list[Window] = []
    for w in windows:
        key = (round(w.start, 1), round(w.end, 1))
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def stride_windows(duration: float, cfg: WindowConfig) -> list[tuple[float, float]]:
    """Fallback for sources with no usable transcript."""
    out: list[tuple[float, float]] = []
    t = 0.0
    while t + cfg.min_s <= duration:
        out.append((t, min(duration, t + cfg.target_s)))
        t += cfg.stride_s
    return out
