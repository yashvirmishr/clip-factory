"""Caption page grouping.

This is a real algorithm, not a formatting step. A page is valid when it can be
read in the time it is on screen, fits the line budget, and does not break a
sentence in half for no reason. Everything here is deterministic so a re-render
is byte-identical.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...config import CaptionConfig
from ...domain import Word


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

    out: list[CaptionPage] = []
    for index, group in enumerate(pages):
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
        out.append(
            CaptionPage(
                index=index,
                start=round(start, 3),
                end=round(end, 3),
                words=[CaptionWord(text=w.text, start=w.start, end=w.end) for w in group],
                lines=lines,
                text=text,
                cps=cps,
                warnings=warnings,
            )
        )
    return out


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
