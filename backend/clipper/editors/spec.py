"""The clip as every editor backend needs to see it.

There are now three consumers of the same decision: the ffmpeg renderer burns
captions, the exporters describe them to an NLE, and the UI shows them. Each one
has its own idea of time - frames, centiseconds, seconds - so they share this
object instead of each re-deriving from the candidate. The cross-format test in
``tests/test_editors.py`` asserts they still agree; that assertion is the only
thing standing between "edited clip" and "captions eight frames early".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import SETTINGS
from ..domain import AnalysisResult, ClipCandidate, SourceInfo
from ..pipeline.caption import CaptionPage, pages_for
from .timecode import Rate, frames_at, rate_for


@dataclass(frozen=True)
class ClipSpec:
    """One clip, resolved once, consumed by every backend."""

    id: str
    name: str
    source_path: Path
    source_name: str
    start: float
    end: float
    hook: str
    title: str
    pages: tuple[CaptionPage, ...]
    rank: int | None = None
    score: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 30.0
    source_duration: float = 0.0
    # Auto-framing knots, clip-relative (time, crop-left in source pixels).
    crop: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    # Per-clip caption style overrides, so a handoff ASS matches the render.
    caption_style: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def rate(self) -> Rate:
        return rate_for(self.fps)

    @property
    def in_frame(self) -> int:
        return frames_at(self.start, self.rate)

    @property
    def out_frame(self) -> int:
        return frames_at(self.end, self.rate)

    @property
    def duration_frames(self) -> int:
        return max(1, self.out_frame - self.in_frame)

    def page_spans(self) -> list[tuple[float, float, str]]:
        """Caption pages in clip-relative seconds, clipped to the clip."""
        spans: list[tuple[float, float, str]] = []
        for page in self.pages:
            start = max(0.0, page.start - self.start)
            end = min(self.duration, page.end - self.start)
            if end - start <= 0.01:
                continue
            spans.append((start, end, page.text))
        return spans

    def file_url(self) -> str:
        """``file://`` reference. Media is referenced, never embedded."""
        return Path(self.source_path).resolve().as_uri()


def _clip_name(index: int, candidate: ClipCandidate) -> str:
    hook = (candidate.llm.hook if candidate.llm else "") or candidate.text
    head = " ".join(hook.split()[:7]).strip().rstrip(",.;:")
    return f"{index:02d} {head}" if head else f"{index:02d} clip"


def spec_for(
    source: SourceInfo,
    candidate: ClipCandidate,
    index: int = 1,
    crop: tuple[tuple[float, float], ...] = (),
) -> ClipSpec:
    pages = pages_for(candidate, SETTINGS.captions)
    return ClipSpec(
        id=candidate.id,
        name=_clip_name(index, candidate),
        source_path=Path(source.path),
        source_name=source.name,
        start=round(candidate.start, 3),
        end=round(candidate.end, 3),
        hook=(candidate.llm.hook if candidate.llm else "") or "",
        title=(candidate.llm.title if candidate.llm else "") or "",
        pages=tuple(pages),
        rank=candidate.rank,
        score=round(candidate.final, 4),
        width=source.width,
        height=source.height,
        fps=source.fps or 30.0,
        source_duration=round(source.duration, 3),
        crop=crop,
        caption_style=dict(candidate.caption_style or {}),
    )


def specs_for(
    source: SourceInfo,
    analysis: AnalysisResult,
    limit: int | None = None,
) -> list[ClipSpec]:
    """Selected clips in rank order. Unranked candidates are not exported."""
    ranked = sorted(
        (c for c in analysis.candidates if c.rank), key=lambda c: c.rank or 0
    )
    if limit:
        ranked = ranked[:limit]
    return [spec_for(source, candidate, index) for index, candidate in enumerate(ranked, 1)]
