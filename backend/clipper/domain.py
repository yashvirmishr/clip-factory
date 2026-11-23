"""Domain models shared across the pipeline and the HTTP API."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

GateSeverity = Literal["block", "warn"]


class Word(BaseModel):
    text: str
    start: float
    end: float
    prob: float = 1.0
    refined: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class Utterance(BaseModel):
    """A sentence-ish unit: the atom the windowing and caption layers use."""

    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)
    question: bool = False
    terminal: bool = True  # ends on terminal punctuation -> safe clip boundary


class SourceInfo(BaseModel):
    id: str
    name: str
    path: str
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = True
    size_bytes: int = 0


class LLMJudgement(BaseModel):
    score: int = 0
    hook: str = ""
    title: str = ""
    reason: str = ""
    understands_standalone: bool = True
    has_payoff: bool = True
    provider: str = "stub"


class GateResult(BaseModel):
    id: str
    passed: bool
    severity: GateSeverity = "block"
    detail: str = ""


class ScoreItem(BaseModel):
    """One row of the visible clip scorecard."""

    id: str
    label: str
    passed: bool
    detail: str = ""


class ClipCandidate(BaseModel):
    id: str
    source_id: str
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)
    features: WindowFeatures | None = None
    fused: float = 0.0
    llm: LLMJudgement | None = None
    final: float = 0.0
    gates: list[GateResult] = Field(default_factory=list)
    scorecard: list[ScoreItem] = Field(default_factory=list)
    rank: int | None = None
    blocked: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def blocking_failures(self) -> list[GateResult]:
        return [g for g in self.gates if not g.passed and g.severity == "block"]

    def scorecard_ratio(self) -> float:
        if not self.scorecard:
            return 1.0
        return sum(1 for s in self.scorecard if s.passed) / len(self.scorecard)


class WindowFeatures(BaseModel):
    """Per-window numbers that both scoring and the learner consume."""

    duration: float = 0.0
    word_count: int = 0
    words_per_sec: float = 0.0
    question_count: int = 0
    exclaim_count: int = 0
    second_person: int = 0
    number_count: int = 0
    hook_lexicon_hits: int = 0
    profanity: int = 0
    caps_ratio: float = 0.0
    mean_word_prob: float = 1.0
    low_conf_ratio: float = 0.0
    speech_coverage: float = 0.0
    start_in_stream: float = 0.0
    end_in_stream: float = 0.0


class AnalysisResult(BaseModel):
    source: SourceInfo
    candidates: list[ClipCandidate]
    asr_backend: str
    llm_backend: str
    duration_s: float = 0.0
    reel_quality: float = 0.0
    warnings: list[str] = Field(default_factory=list)


def stable_id(*parts: object) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def clip_id(source_id: str, start: float, end: float) -> str:
    return stable_id(source_id, f"{start:.3f}", f"{end:.3f}")
