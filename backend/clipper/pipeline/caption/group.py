"""Caption page grouping.

This is a real algorithm, not a formatting step. A page is valid when it can be
read in the time it is on screen, fits the line budget, and does not break a
sentence in half for no reason. Everything here is deterministic so a re-render
is byte-identical.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field, ValidationError

from ...config import CaptionConfig
from ...domain import ClipCandidate, Word


class CaptionWord(BaseModel):
    text: str
    start: float
    end: float


class CaptionPage(BaseModel):
    index: int
    start: float
    end: float
    words: list[CaptionWord] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)
    text: str = ""
    cps: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _char_count(text: str) -> int:
    return len(text.replace(" ", ""))


def _wrap(words: list[str], max_chars: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in words:
        candidate = f"{current} {token}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:max_lines] if lines else []


def _ends_sentence(text: str) -> bool:
    return text.strip().endswith((".", "!", "?", "…"))


def group_words(words: list[Word], cfg: CaptionConfig | None = None) -> list[CaptionPage]:
    cfg = cfg or CaptionConfig()
    ordered = sorted(words, key=lambda w: w.start)
    pages: list[list[Word]] = []
    current: list[Word] = []

    for word in ordered:
        if current:
            previous = current[-1]
            gap = word.start - previous.end
            projected = current + [word]
            text = " ".join(w.text for w in projected)
            span = max(0.05, word.end - current[0].start)
            cps = _char_count(text) / span
            over_length = len(text) > cfg.max_chars_per_line * cfg.max_lines
            too_many = len(current) >= cfg.max_words
            sentence_done = _ends_sentence(previous.text) and len(current) >= cfg.min_words
            would_over_cps = cps > cfg.cps_limit and len(current) >= cfg.min_words
            if gap > cfg.gap_split_s or too_many or over_length or sentence_done or would_over_cps:
                pages.append(current)
                current = []
        current.append(word)

    if current:
        pages.append(current)

    pages = _merge_short_pages(pages, cfg)

    return [
        _page_for(
            index,
            [CaptionWord(text=w.text, start=w.start, end=w.end) for w in group],
            cfg,
        )
        for index, group in enumerate(pages)
    ]


def _page_for(index: int, group: list[CaptionWord], cfg: CaptionConfig) -> CaptionPage:
    """Build one page from words that already share a screen.

    Grouping and manual editing both come through here, so a hand-edited page
    gets the same wrapping, CPS and warning rules as a generated one.
    """
    text = " ".join(w.text for w in group)
    start, end = group[0].start, group[-1].end
    span = max(0.05, end - start)
    cps = round(_char_count(text) / span, 1)
    lines = _wrap([w.text for w in group], cfg.max_chars_per_line, cfg.max_lines)
    warnings: list[str] = []
    if cps > cfg.cps_limit:
        warnings.append(f"cps {cps:.0f} exceeds {cfg.cps_limit:.0f}")
    if any(len(line) > cfg.max_chars_per_line for line in lines):
        warnings.append("line too long")
    if len(" ".join(lines).split()) < len(group):
        warnings.append("text clipped by line budget")
    if end - start < cfg.min_page_s:
        warnings.append("page too short")
    return CaptionPage(
        index=index,
        start=round(start, 3),
        end=round(end, 3),
        words=group,
        lines=lines,
        text=text,
        cps=cps,
        warnings=warnings,
    )


_MAX_EDIT_PAGES = 500
_MAX_EDIT_WORDS = 200
_MAX_WORD_CHARS = 120
# Alignment jitter at page boundaries is normal; a dragged page is not.
_OVERLAP_TOLERANCE = 0.05


def edit_pages(
    groups: list[list[CaptionWord]],
    clip_start: float,
    clip_end: float,
    cfg: CaptionConfig | None = None,
) -> list[CaptionPage]:
    """Turn an editor's page groups into validated caption pages.

    The editor sends words, not rendered pages: page bounds, wrapping, CPS and
    warnings are derived here so a client cannot save a page that disagrees with
    the words it displays. Words are clipped to the clip and pulled forward
    enough to remove ASR jitter; a page dragged well into the previous one is
    refused, because two ASS events on screen at once is not an edit, it is a
    bug.
    """
    cfg = cfg or CaptionConfig()
    start_bound = float(clip_start)
    end_bound = float(clip_end)
    if not math.isfinite(start_bound) or not math.isfinite(end_bound):
        raise ValueError("clip bounds must be finite")
    if end_bound - start_bound <= 0.0:
        raise ValueError("clip has no usable duration")
    if not groups:
        raise ValueError("at least one caption page is required")
    if len(groups) > _MAX_EDIT_PAGES:
        raise ValueError(f"too many caption pages (max {_MAX_EDIT_PAGES})")

    out: list[CaptionPage] = []
    previous_word_end = start_bound
    previous_page_end = start_bound
    for index, group in enumerate(groups):
        if not group:
            raise ValueError(f"page {index + 1} has no words")
        if len(group) > _MAX_EDIT_WORDS:
            raise ValueError(f"page {index + 1} has too many words")
        group = sorted(group, key=lambda word: (word.start, word.end))

        # A word that starts a page a long way inside the previous one is a
        # mistake; a few milliseconds is just the ASR's timing jitter.
        if index and group[0].start < previous_page_end - _OVERLAP_TOLERANCE:
            raise ValueError("caption pages overlap")

        words: list[CaptionWord] = []
        for raw in group:
            text = " ".join(raw.text.split())
            if not text:
                raise ValueError(f"page {index + 1} has an empty word")
            if len(text) > _MAX_WORD_CHARS:
                raise ValueError(f"page {index + 1} has an overlong word")
            word_start = float(raw.start)
            word_end = float(raw.end)
            if not math.isfinite(word_start) or not math.isfinite(word_end):
                raise ValueError(f"page {index + 1} has a non-finite timestamp")
            if word_end <= start_bound or word_start >= end_bound:
                raise ValueError(f"page {index + 1} has a word outside the clip")
            word_start = max(word_start, start_bound, previous_word_end)
            word_end = min(word_end, end_bound)
            if word_end - word_start < 0.02:
                raise ValueError(f"page {index + 1} has a word with no room left")
            words.append(
                CaptionWord(
                    text=text,
                    start=round(word_start, 3),
                    end=round(word_end, 3),
                )
            )
            previous_word_end = word_end

        page = _page_for(index, words, cfg)
        out.append(page)
        previous_page_end = page.end

    return out


def pages_for(
    candidate: ClipCandidate, cfg: CaptionConfig | None = None
) -> list[CaptionPage]:
    """A clip's pages: the manual edit if it is valid, otherwise the grouping."""
    if candidate.caption_pages:
        try:
            return [CaptionPage.model_validate(page) for page in candidate.caption_pages]
        except (ValidationError, TypeError, ValueError):
            # A stale or hand-corrupted override must not take the render down;
            # fall back to the transcript and keep the clip editable.
            pass
    return group_words(candidate.words, cfg)


def _merge_short_pages(pages: list[list[Word]], cfg: CaptionConfig) -> list[list[Word]]:
    """Fold pages that flash on screen into their neighbour.

    A single 6-character word at 0.3 s is 20 cps and below the minimum page
    duration - technically valid, visually a flicker. Merging is only allowed
    while the result still respects the word and character budgets.
    """
    merged: list[list[Word]] = []
    char_budget = cfg.max_chars_per_line * cfg.max_lines
    for group in pages:
        if merged and group:
            previous = merged[-1]
            previous_duration = previous[-1].end - previous[0].start
            duration = group[-1].end - group[0].start
            gap = group[0].start - previous[-1].end
            combined = previous + group
            chars = len(" ".join(word.text for word in combined))
            span = max(combined[-1].end - combined[0].start, 1e-3)
            short = previous_duration < cfg.min_page_s or duration < cfg.min_page_s
            if (
                short
                and gap <= cfg.gap_split_s
                and len(combined) <= cfg.max_words
                and chars <= char_budget
                and chars / span <= cfg.cps_limit
            ):
                merged[-1] = combined
                continue
        merged.append(list(group))

    return _pad_short_pages(merged, cfg)


def _pad_short_pages(pages: list[list[Word]], cfg: CaptionConfig) -> list[list[Word]]:
    """Hold a page on screen long enough to read.

    Padding only borrows silence: it never runs past the next page or past the
    clip, so it cannot make two captions collide.
    """
    out: list[list[Word]] = []
    for index, group in enumerate(pages):
        if not group:
            out.append(group)
            continue
        group = list(group)
        span = group[-1].end - group[0].start
        if span < cfg.min_page_s:
            target = group[0].start + cfg.min_page_s
            if index + 1 < len(pages) and pages[index + 1]:
                target = min(target, pages[index + 1][0].start - 0.02)
            if target > group[-1].end:
                group[-1] = group[-1].model_copy(update={"end": target})
        out.append(group)
    return out


def caption_stats(pages: list[CaptionPage]) -> dict:
    if not pages:
        return {"pages": 0, "mean_cps": 0.0, "warnings": 0}
    return {
        "pages": len(pages),
        "mean_cps": round(sum(p.cps for p in pages) / len(pages), 1),
        "warnings": sum(len(p.warnings) for p in pages),
    }
