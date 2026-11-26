"""Word-level timing refinement.

whisper.cpp (and every subtitle cue) gives timings that are *close* rather than
correct. Three cheap passes fix most of the drift, without a second model:

1. monotonic clamp  - words cannot overlap or run backwards
2. silence snapping - boundaries are pulled to the nearest energy trough
3. outlier repair   - durations far from the local median are re-interpolated
"""

from __future__ import annotations

import bisect

import numpy as np

from ..domain import Word
from .media import AudioAnalysis

MIN_WORD_S = 0.045


def _local_trough(rms: np.ndarray, frame_rate: float, t: float, search_s: float) -> float:
    """Nearest energy minimum within ±search_s of ``t`` (in seconds).

    Returns ``t`` unchanged when the window is flat - snapping to the first
    sample of a tie would silently drag every boundary backwards.
    """
    if rms.size == 0:
        return t
    centre = int(round(t * frame_rate))
    radius = max(1, int(round(search_s * frame_rate)))
    lo = max(0, centre - radius)
    hi = min(rms.size, centre + radius + 1)
    if hi <= lo:
        return t
    window = rms[lo:hi]
    idx = lo + int(np.argmin(window))
    centre_idx = min(max(centre, lo), hi - 1)
    centre_value = float(rms[centre_idx])
    if rms[idx] > centre_value * 0.9:
        return t
    return idx / frame_rate


def refine_words(
    words: list[Word],
    analysis: AudioAnalysis | None,
    snap_s: float = 0.12,
    outlier_factor: float = 2.5,
) -> list[Word]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w.start)
    out: list[Word] = []

    for word in ordered:
        start, end = word.start, max(word.start + MIN_WORD_S, word.end)
        if out:
            start = max(start, out[-1].end - 0.02)
            start = max(start, out[-1].start + MIN_WORD_S)
        end = max(end, start + MIN_WORD_S)

        if analysis is not None and analysis.rms.size:
            start = _local_trough(analysis.rms, analysis.frame_rate, start, snap_s)
            end = _local_trough(analysis.rms, analysis.frame_rate, end, snap_s)
            if out:
                start = max(start, out[-1].end - 0.02)
            end = max(end, start + MIN_WORD_S)

        out.append(word.model_copy(update={"start": round(start, 3), "end": round(end, 3)}))

    return _repair_durations(out, outlier_factor)


def _repair_durations(words: list[Word], factor: float) -> list[Word]:
    durations = np.array([w.duration for w in words], dtype=np.float32)
    if durations.size < 4:
        return words
    median = float(np.median(durations))
    if median <= 0:
        return words

    repaired: list[Word] = []
    for i, word in enumerate(words):
        lo, hi = max(0, i - 2), min(len(words) - 1, i + 2)
        neighbours = [durations[j] for j in range(lo, hi + 1) if j != i]
        reference = float(np.median(neighbours)) if neighbours else median
        duration = word.duration
        if duration > median * factor or duration < median / factor:
            target_end = word.start + reference
            if i + 1 < len(words):
                target_end = min(target_end, words[i + 1].start + 0.02)
            word = word.model_copy(update={"end": round(max(word.start + MIN_WORD_S, target_end), 3)})
        repaired.append(word.model_copy(update={"refined": True}))
    return repaired


def words_in_range(words: list[Word], start: float, end: float) -> list[Word]:
    return WordIndex(words).between(start, end)


class WordIndex:
    """Binary-search slices of a start-sorted word list.

    A two-hour source has ~20k words and every window used to scan all of them,
    which is millions of comparisons per analysis. Windows arrive in order, but
    a plain bisect on the start times is enough and stays correct if they do not.
    """

    __slots__ = ("words", "starts")

    def __init__(self, words: list[Word]) -> None:
        self.words = words
        self.starts = [word.start for word in words]

    def between(self, start: float, end: float) -> list[Word]:
        if not self.words or end <= start:
            return []
        hi = bisect.bisect_left(self.starts, end)
        lo = hi
        # A word that begins before this window may still reach into it.
        while lo > 0 and self.words[lo - 1].end > start:
            lo -= 1
        return self.words[lo:hi]


def flat_words(utterances: list) -> list[Word]:
    words: list[Word] = []
    for utterance in utterances:
        words.extend(utterance.words)
    return words
