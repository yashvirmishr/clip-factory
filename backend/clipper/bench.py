"""Pick-quality benchmark: does the pipeline choose the moments a human would?

The scorecard measures a *clip* - is it self-contained, does it open on a hook.
It says nothing about whether the picker chose the right five moments out of two
hours, which is the thing users actually judge. This module scores picks against
hand-labelled moments and reports precision, recall and duplicate grabs.

Two design choices worth knowing:

* a pick matches a labelled moment when it covers at least ``threshold`` of that
  moment's span. Partial credit was tempting and is wrong: a clip that catches
  the last 3 seconds of a story is not that story.
* two picks landing on the same moment both count against precision. Grabbing the
  same beat twice is the second-most common failure after missing it entirely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_THRESHOLD = 0.4


@dataclass(frozen=True)
class GoldMoment:
    start: float
    end: float
    label: str = ""
    weight: float = 1.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class GoldSet:
    source: str
    moments: list[GoldMoment]
    notes: str = ""

    @property
    def total_weight(self) -> float:
        return sum(moment.weight for moment in self.moments)


@dataclass
class Match:
    gold: GoldMoment
    clip_start: float
    clip_end: float
    overlap: float
    duplicate: bool = False


@dataclass
class Report:
    gold_count: int
    clip_count: int
    matches: list[Match] = field(default_factory=list)
    missing: list[GoldMoment] = field(default_factory=list)

    @property
    def hits(self) -> int:
        return sum(1 for match in self.matches if not match.duplicate)

    @property
    def duplicates(self) -> int:
        return sum(1 for match in self.matches if match.duplicate)

    @property
    def precision(self) -> float:
        if not self.clip_count:
            return 0.0
        return round(self.hits / self.clip_count, 4)

    @property
    def recall(self) -> float:
        return round(self.hits / self.gold_count, 4) if self.gold_count else 0.0

    @property
    def f1(self) -> float:
        precision, recall = self.precision, self.recall
        if precision + recall <= 0:
            return 0.0
        return round(2 * precision * recall / (precision + recall), 4)

    @property
    def coverage(self) -> float:
        hits = [match.overlap for match in self.matches if not match.duplicate]
        return round(sum(hits) / len(hits), 4) if hits else 0.0

    def to_dict(self) -> dict:
        return {
            "gold": self.gold_count,
            "clips": self.clip_count,
            "hits": self.hits,
            "duplicates": self.duplicates,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "coverage": self.coverage,
            "missing": [round(moment.start, 2) for moment in self.missing],
        }

    def summary_line(self, name: str = "") -> str:
        return (
            f"{name or 'reel':28s} "
            f"P@k {self.precision:5.2f}  R {self.recall:5.2f}  F1 {self.f1:5.2f}  "
            f"cov {self.coverage:4.2f}  dup {self.duplicates}  "
            f"missing {len(self.missing)}"
        )


def load(path: str | Path) -> GoldSet:
    payload = json.loads(Path(path).read_text("utf-8"))
    moments = [
        GoldMoment(
            start=float(item["start"]),
            end=float(item["end"]),
            label=item.get("label", ""),
            weight=float(item.get("weight", 1.0)),
        )
        for item in payload["moments"]
    ]
    return GoldSet(
        source=payload["source"],
        moments=sorted(moments, key=lambda moment: moment.start),
        notes=payload.get("notes", ""),
    )


def overlap_ratio(clip: tuple[float, float], moment: GoldMoment) -> float:
    """Share of the *labelled moment* a clip covers."""
    start, end = clip
    if moment.duration <= 0:
        return 0.0
    left = max(start, moment.start)
    right = min(end, moment.end)
    return max(0.0, right - left) / moment.duration


def evaluate(
    clips: list[tuple[float, float]],
    gold: GoldSet,
    threshold: float = DEFAULT_THRESHOLD,
) -> Report:
    report = Report(gold_count=len(gold.moments), clip_count=len(clips))
    claimed: set[int] = set()

    for clip in clips:
        best_index = -1
        best_overlap = 0.0
        for index, moment in enumerate(gold.moments):
            ratio = overlap_ratio(clip, moment)
            if ratio >= threshold and ratio > best_overlap:
                best_index, best_overlap = index, ratio
        if best_index < 0:
            continue
        report.matches.append(
            Match(
                gold=gold.moments[best_index],
                clip_start=clip[0],
                clip_end=clip[1],
                overlap=round(best_overlap, 4),
                duplicate=best_index in claimed,
            )
        )
        claimed.add(best_index)

    report.missing = [
        moment for index, moment in enumerate(gold.moments) if index not in claimed
    ]
    return report


def evaluate_result(
    result,
    gold: GoldSet,
    limit: int | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> Report:
    """Score the ranked reel from one analysis against a gold set."""
    ranked = sorted(
        (candidate for candidate in result.candidates if candidate.rank),
        key=lambda candidate: candidate.rank or 0,
    )
    if limit:
        ranked = ranked[:limit]
    return evaluate([(c.start, c.end) for c in ranked], gold, threshold)


def discover(directory: str | Path) -> list[tuple[Path, GoldSet]]:
    out: list[tuple[Path, GoldSet]] = []
    for path in sorted(Path(directory).glob("*.json")):
        out.append((path, load(path)))
    return out
