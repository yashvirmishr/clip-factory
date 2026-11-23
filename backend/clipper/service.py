"""Orchestration: the analysis pipeline as one resumable function.

Each stage writes its artifact to disk keyed by source id, so re-running an
analysis is free and a crash mid-way only loses the stage that was in flight.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

import numpy as np

from . import db
from .config import SETTINGS
from .domain import (
    AnalysisResult,
    ClipCandidate,
    GateResult,
    SourceInfo,
    WindowFeatures,
    clip_id,
    stable_id,
)
from .learn import LEARNER
from .llm import resolve_scorer
from .pipeline.align import flat_words, refine_words, words_in_range
from .pipeline.asr import StubASR, resolve_backend
from .pipeline.gates import evaluate_gates
from .pipeline.media import (
    compute_features,
    extract_audio,
    load_peaks,
    peak_pyramid,
    probe,
)
from .pipeline.scorecard import build_scorecard, grounding_ratio, reel_quality
from .pipeline.select import diversify_order, select_clips
from .pipeline.signals import (
    blend_with_llm,
    fuse,
    load_chat_rate,
    normalise_signals,
    raw_signals,
    window_features,
)
from .pipeline.windows import build_windows
from .textvec import cosine, starts_with_deictic, vector

Progress = Callable[[str, float, str], None]


def _noop(stage: str, pct: float, detail: str = "") -> None:  # pragma: no cover
    return


def worker_threads() -> int:
    cpus = os.cpu_count() or 4
    return max(1, cpus - SETTINGS.hardware.reserve_threads)


def ingest(path: str | Path, name: str | None = None) -> SourceInfo:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"not found: {path}")
    info = probe(path)
    source_id = stable_id(path.resolve(), info["size_bytes"], round(info["duration"], 2))
    return db.upsert_source(
        SourceInfo(
            id=source_id,
            name=name or path.name,
            path=str(path.resolve()),
            duration=info["duration"],
            width=info["width"],
            height=info["height"],
            fps=info["fps"],
            has_audio=info["has_audio"],
            size_bytes=info["size_bytes"],
        )
    )


def artifacts_for(source_id: str) -> Path:
    out = SETTINGS.artifacts_dir() / source_id
    out.mkdir(parents=True, exist_ok=True)
    return out


def ensure_audio_artifacts(source: SourceInfo, progress: Progress) -> tuple[Path, Path]:
    work = artifacts_for(source.id)
    wav = work / "audio.wav"
    peaks = work / "peaks.npz"
    progress("audio", 0.05, "extracting 16 kHz mono")
    extract_audio(source.path, wav, SETTINGS.audio)
    if not peaks.exists():
        progress("audio", 0.12, "building peak pyramid")
        np.savez_compressed(peaks, **peak_pyramid(wav))
    return wav, peaks


def _transcribe(
    source: SourceInfo,
    wav: Path,
    subtitle_path: str | Path | None,
    progress: Progress,
    duration: float,
):
    backend = resolve_backend(
        whisper_cli=SETTINGS.whisper_cli,
        whisper_model=SETTINGS.whisper_model_path,
        vad_model=SETTINGS.vad_model_path,
        subtitle_path=subtitle_path,
        threads=worker_threads(),
    )
    progress("transcribe", 0.2, f"backend: {backend.name}")
    cache = artifacts_for(source.id) / "transcript.json"
    if cache.exists():
        try:
            payload = json.loads(cache.read_text("utf-8"))
            from .domain import Utterance

            utterances = [Utterance.model_validate(u) for u in payload["utterances"]]
            return utterances, payload.get("asr_backend", backend.name)
        except (KeyError, ValueError, OSError):
            pass

    if isinstance(backend, StubASR):
        result = backend.transcribe(duration=duration)
    else:
        result = backend.transcribe(wav, artifacts_for(source.id)) if hasattr(backend, "build_command") else backend.transcribe()

    cache.write_text(
        json.dumps(
            {
                "asr_backend": result.backend,
                "utterances": [u.model_dump() for u in result.utterances],
            }
        ),
        "utf-8",
    )
    progress("transcribe", 0.45, f"{len(result.utterances)} utterances")
    return result.utterances, result.backend


def build_shortlist(candidates: list[ClipCandidate], budget: int) -> list[ClipCandidate]:
    """Top candidates by signal score, pre-deduplicated.

    Without this the scoring budget is spent on five variations of the same
    moment, which starves the final selection after overlap rejection.
    """
    ordered = sorted(candidates, key=lambda c: c.fused, reverse=True)
    picked: list[ClipCandidate] = []
    vectors: list[np.ndarray] = []
    for candidate in ordered:
        if len(picked) >= budget:
            break
        if candidate.blocked:
            continue
        v = vector(candidate.text)
        if any(cosine(v, other) >= SETTINGS.gates.dedupe_cosine for other in vectors):
            continue
        if any(
            max(0.0, min(candidate.end, p.end) - max(candidate.start, p.start))
            / max(1e-6, min(candidate.end - candidate.start, p.end - p.start))
            > SETTINGS.gates.max_overlap_ratio
            for p in picked
        ):
            continue
        picked.append(candidate)
        vectors.append(v)
    return picked


def analyze(
    source: SourceInfo,
    *,
    subtitle_path: str | Path | None = None,
    chat_path: str | Path | None = None,
    limit: int = 10,
    progress: Progress | None = None,
    force: bool = False,
) -> AnalysisResult:
    progress = progress or _noop
    warnings: list[str] = []

    if not force:
        cached = db.get_analysis(source.id)
        if cached is not None:
            progress("cached", 1.0, "using cached analysis")
            return cached

    wav, peaks_path = ensure_audio_artifacts(source, progress)

    progress("audio", 0.16, "computing energy / flux / zcr")
    analysis = compute_features(wav, SETTINGS.audio)

    utterances, asr_backend = _transcribe(source, wav, subtitle_path, progress, source.duration)
    if asr_backend == "stub":
        warnings.append(
            "No ASR available - ran with the deterministic stub transcript. "
            "Install whisper.cpp (or import an .srt) for real results."
        )

    progress("align", 0.5, "refining word timings")
    all_words = refine_words(flat_words(utterances), analysis)

    progress("windows", 0.56, "building sentence-aligned windows")
    windows = build_windows(utterances, SETTINGS.windows)
    if not windows:
        warnings.append("No speech found above the window threshold.")
        empty = AnalysisResult(
            source=source,
            candidates=[],
            asr_backend=asr_backend,
            llm_backend="none",
            duration_s=0.0,
            warnings=warnings,
        )
        db.save_analysis(empty)
        return empty

    chat = load_chat_rate(chat_path, source.duration)
    available = {"audio", "excitement", "speech", "hook_lexicon"}
    if chat is not None:
        available.add("chat")
    else:
        warnings.append("No chat replay - chat weight redistributed to other signals.")

    progress("signals", 0.64, f"scoring {len(windows)} windows")
    raw: dict[str, list[float]] = {k: [] for k in ("audio", "excitement", "chat", "speech", "hook_lexicon")}
    features_list: list[WindowFeatures] = []
    words_by_window: list[list] = []
    for window in windows:
        words = words_in_range(all_words, window.start, window.end)
        feats = window_features(
            window.text, window.start, window.end,
            [w.prob for w in words], analysis,
        )
        features_list.append(feats)
        words_by_window.append(words)
        signals = raw_signals(feats, analysis, chat)
        for key in raw:
            raw[key].append(signals[key])

    normalised = normalise_signals(raw, available)
    scored: list[ClipCandidate] = []
    for window, feats, sig, words in zip(windows, features_list, normalised, words_by_window):
        fused = fuse(sig, SETTINGS.weights, available)
        window.starts_with_deictic = starts_with_deictic(window.text) is not None
        scored.append(
            ClipCandidate(
                id=clip_id(source.id, window.start, window.end),
                source_id=source.id,
                start=window.start,
                end=window.end,
                text=window.text,
                words=words,
                signals=sig,
                fused=fused,
                features=feats,
            )
        )

    # ---- gates ---------------------------------------------------------
    progress("gates", 0.72, "applying quality gates")
    for candidate, window, feats, words in zip(scored, windows, features_list, words_by_window):
        gates = evaluate_gates(window, feats, words, SETTINGS.gates, source.duration)
        candidate.gates = gates
        candidate.blocked = any(not g.passed and g.severity == "block" for g in gates)

    # ---- LLM scoring on a diverse shortlist only -----------------------
    # Spend the prompt budget on distinct moments, and let selection draw only
    # from scored candidates - otherwise an unscored window whose raw signal
    # score beats a blended one can win a slot with no judgement behind it.
    scorer = resolve_scorer(SETTINGS.llama_url)
    profile = LEARNER.style_profile()
    shortlist = build_shortlist(scored, max(12, limit * 3))
    shortlisted_ids = {c.id for c in shortlist}

    for candidate in scored:
        if candidate.id not in shortlisted_ids:
            candidate.gates.append(
                GateResult(
                    id="not_shortlisted",
                    passed=False,
                    severity="warn",
                    detail="outside the scoring budget for this run",
                )
            )
            candidate.blocked = True

    for index, candidate in enumerate(shortlist):
        exemplars = LEARNER.exemplars(candidate.text)
        judgement = scorer.score(
            candidate.text, candidate.start, candidate.end,
            candidate.features or WindowFeatures(), exemplars, profile,
        )
        candidate.llm = judgement
        candidate.final = blend_with_llm(
            candidate.fused, judgement.score,
            SETTINGS.blend.signal_weight, SETTINGS.blend.llm_weight,
        )
        if index % 4 == 0:
            progress("score", 0.78 + 0.12 * (index / max(1, len(shortlist))), f"{index}/{len(shortlist)} windows")

    # ---- personal re-ranker -------------------------------------------
    LEARNER.rerank(shortlist)

    # ---- selection -----------------------------------------------------
    progress("select", 0.92, "picking non-overlapping clips")
    selected, dropped = select_clips(shortlist, SETTINGS.gates, limit=limit)
    selected = diversify_order(selected)
    for rank, candidate in enumerate(selected, start=1):
        candidate.rank = rank

    # ---- grounding + scorecard ----------------------------------------
    for candidate in selected + dropped:
        hook = candidate.llm.hook if candidate.llm else ""
        ratio = grounding_ratio(hook, candidate.text) if hook else 0.0
        candidate.scorecard = build_scorecard(candidate, candidate.features or WindowFeatures(), ratio)
        if candidate.llm and not candidate.llm.understands_standalone:
            candidate.gates.append(
                GateResult(
                    id="llm_critique",
                    passed=False,
                    severity="warn",
                    detail="model judged it may not stand alone",
                )
            )

    rejected_non_shortlist = [c for c in scored if c.id not in shortlisted_ids]
    result = AnalysisResult(
        source=source,
        candidates=selected + dropped + rejected_non_shortlist,
        asr_backend=asr_backend,
        llm_backend=scorer.name,
        duration_s=float(analysis.duration),
        reel_quality=reel_quality(selected),
        warnings=warnings,
    )
    db.save_analysis(result)
    progress("done", 1.0, f"{len(selected)} clips from {len(scored)} windows")
    return result


def peaks_for(source_id: str, level: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    path = artifacts_for(source_id) / "peaks.npz"
    if not path.exists():
        raise FileNotFoundError("peaks not built yet")
    return load_peaks(path, level)
