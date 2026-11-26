"""Orchestration: the analysis pipeline as one resumable function.

Each stage writes its artifact to disk keyed by source id, so re-running an
analysis is free and a crash mid-way only loses the stage that was in flight.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from . import db, policy
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
from .lang import normalise, script_for_language
from .learn import LEARNER
from .llm import resolve_scorer
from .pipeline.align import WordIndex, flat_words, refine_words
from .pipeline.asr import StubASR, resolve_backend
from .pipeline.gates import evaluate_gates
from .pipeline.media import (
    FFMPEG,
    compute_features,
    extract_audio,
    load_peaks,
    peak_pyramid,
    probe,
)
from .pipeline.scorecard import build_scorecard, grounding_ratio, reel_quality
from .pipeline.scenes import cuts_for
from .pipeline.select import diversify_order, select_clips
from .pipeline.signals import (
    blend_with_llm,
    fuse,
    load_chat_rate,
    normalise_signals,
    raw_signals,
    window_features,
)
from .pipeline.windows import Window, build_windows, snap_windows
from .textvec import cosine, starts_with_deictic, vector

Progress = Callable[[str, float, str], None]


def _noop(stage: str, pct: float, detail: str = "") -> None:  # pragma: no cover
    return


def worker_threads() -> int:
    cpus = os.cpu_count() or 4
    return max(1, cpus - SETTINGS.hardware.reserve_threads)


def ingest(
    path: str | Path,
    name: str | None = None,
    progress: Progress | None = None,
) -> SourceInfo:
    """Register a source. A URL is fetched first, into the app media folder."""
    from .pipeline import fetch

    origin = str(path).strip() if fetch.is_url(path) else ""
    if fetch.is_url(path):
        def download(fraction: float, detail: str) -> None:
            if progress:
                progress("download", fraction, detail)

        fetched = fetch.fetch(str(path), SETTINGS.media_dir(), progress=download)
        path = fetched.path
        name = name or fetched.title
        if progress:
            progress("download", 1.0, f"{fetched.title[:60]}")

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
            origin_url=origin,
        )
    )


CHAT_FILE = "chat.json"
PROXY_FILE = "preview.mp4"


def proxy_path_for(source: SourceInfo) -> Path:
    return artifacts_for(source.id) / PROXY_FILE


def build_proxy(source: SourceInfo, progress: Progress | None = None) -> Path:
    """A 720p browsing copy, so the monitor and thumbnails never seek a 20 GB master.

    The renderer keeps reading the master; this file exists only for the player.
    """

    out = proxy_path_for(source)
    if out.exists() and out.stat().st_size > 10_000:
        return out
    if progress:
        progress("proxy", 0.1, "720p preview copy")
    result = subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", source.path,
            "-vf", "scale=-2:720",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if result.returncode != 0 or not out.exists() or out.stat().st_size < 10_000:
        raise RuntimeError(f"could not build a preview copy: {result.stderr.strip()[:300]}")
    if progress:
        progress("proxy", 1.0, "preview ready")
    return out


def chat_path_for(source: SourceInfo) -> Path | None:
    """The stored chat replay for a source, if one was fetched or dropped in."""
    path = artifacts_for(source.id) / CHAT_FILE
    return path if path.exists() else None


def chat_status(source: SourceInfo) -> dict:
    """Whether this source has chat, and where it would come from."""
    from .pipeline import chat as chatmod

    path = chat_path_for(source)
    offsets = chatmod.read_offsets(path) if path else []
    info = chatmod.coverage(offsets, source.duration)
    info["available"] = bool(offsets)
    info["origin_url"] = source.origin_url
    info["twitch_vod"] = chatmod.vod_id(source.origin_url or "")
    return info


def fetch_chat(
    source: SourceInfo,
    url: str | None = None,
    progress: Progress | None = None,
) -> dict:
    """Download the chat replay for this source and store it as an artifact."""
    from .pipeline import chat as chatmod

    target = url or source.origin_url
    video_id = chatmod.vod_id(target or "")
    if not video_id:
        raise chatmod.ChatError(
            "chat replay only exists for Twitch VODs - give a twitch.tv/videos/<id> URL"
        )

    def report(fraction: float, detail: str) -> None:
        if progress:
            progress("chat", fraction, detail)

    info = chatmod.fetch(target, artifacts_for(source.id) / CHAT_FILE, progress=report,
                         client=None, max_comments=chatmod.MAX_COMMENTS)
    info["available"] = True
    return info


def artifacts_for(source_id: str) -> Path:
    out = SETTINGS.artifacts_dir() / source_id
    out.mkdir(parents=True, exist_ok=True)
    return out


ORIGIN_FILE = "origin.json"
SUBTITLE_DIR = "subtitles"


def subtitles_dir(source: SourceInfo) -> Path:
    out = artifacts_for(source.id) / SUBTITLE_DIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def stored_subtitles(source: SourceInfo) -> list[dict]:
    """Caption tracks already on disk, with cue counts read cheaply."""
    folder = subtitles_dir(source)
    out: list[dict] = []
    for path in sorted(folder.glob("*.vtt")):
        try:
            text = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        out.append(
            {
                "language": path.stem,
                "path": str(path),
                "cues": text.count("-->"),
                "bytes": path.stat().st_size,
            }
        )
    return out


def fetch_subtitles(
    source: SourceInfo,
    language: str,
    automatic: bool = False,
    progress: Progress | None = None,
) -> dict:
    """Download one caption track for a URL source and keep it with the artifacts."""
    from .pipeline import fetch as fetchmod

    if not source.origin_url:
        raise ValueError("this source was not imported from a URL")
    if progress:
        progress("subtitles", 0.15, f"captions: {language}")
    path = fetchmod.fetch_subtitles(
        source.origin_url, language, automatic, subtitles_dir(source)
    )
    if progress:
        progress("subtitles", 1.0, path.name)
    return {
        "path": str(path),
        "language": path.stem,
        "cues": path.read_text("utf-8", errors="replace").count("-->"),
    }


def store_preview(source: SourceInfo, preview: dict) -> None:
    target = artifacts_for(source.id) / ORIGIN_FILE
    target.write_text(json.dumps(preview, indent=2), "utf-8")


def stored_preview(source: SourceInfo) -> dict | None:
    path = artifacts_for(source.id) / ORIGIN_FILE
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


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


def transcript_cache_path(
    source: SourceInfo,
    language: str,
    translate: bool,
    subtitle_path: str | Path | None,
    backend: str = "",
) -> Path:
    """One cache file per (language, model, engine, mode, subtitle).

    The old `transcript.json` was language-blind: running Hindi after English
    returned the English words with no sign that it had done so. The engine is
    part of the key for the same reason: a stub run must never reuse a real
    whisper transcript, or a forced stub analysis silently reports real words.
    """

    model = Path(SETTINGS.whisper_model_path or "").stem or "none"
    subtitle = "none"
    if subtitle_path:
        candidate = Path(subtitle_path)
        try:
            subtitle = stable_id(str(candidate.resolve()), candidate.stat().st_mtime)
        except OSError:
            subtitle = stable_id(str(candidate))
    mode = "tr" if translate else "orig"
    engine = "".join(ch if ch.isalnum() else "-" for ch in backend.strip().lower()) or "auto"
    return artifacts_for(source.id) / (
        f"transcript.{normalise(language)}.{model}.{engine}.{mode}.{subtitle}.json"
    )


def _transcribe(
    source: SourceInfo,
    wav: Path,
    subtitle_path: str | Path | None,
    progress: Progress,
    duration: float,
    language: str = "auto",
    translate: bool = False,
):
    from .hardware import find_whisper_cli

    backend = resolve_backend(
        whisper_cli=SETTINGS.whisper_cli or find_whisper_cli([SETTINGS.data_dir / "bin"]),
        whisper_model=SETTINGS.whisper_model_path,
        vad_model=SETTINGS.vad_model_path,
        subtitle_path=subtitle_path,
        threads=worker_threads(),
        language=language,
        translate=translate,
    )
    progress("transcribe", 0.2, f"backend: {backend.name}")
    cache = transcript_cache_path(source, language, translate, subtitle_path, backend.name)
    if cache.exists():
        try:
            payload = json.loads(cache.read_text("utf-8"))
            from .domain import Utterance

            utterances = [Utterance.model_validate(u) for u in payload["utterances"]]
            return (
                utterances,
                payload.get("asr_backend", backend.name),
                payload.get("language", normalise(language)),
            )
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
                "language": result.language or normalise(language),
                "model": Path(SETTINGS.whisper_model_path or "").name,
                "translate": translate,
                "subtitle_path": str(subtitle_path or ""),
                "utterances": [u.model_dump() for u in result.utterances],
            }
        ),
        "utf-8",
    )
    progress("transcribe", 0.45, f"{len(result.utterances)} utterances")
    return result.utterances, result.backend, result.language or normalise(language)


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
    language: str = "auto",
    translate: bool = False,
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

    utterances, asr_backend, detected_language = _transcribe(
        source, wav, subtitle_path, progress, source.duration,
        language=language, translate=translate,
    )
    # Gates judge script against what the transcript actually turned out to be.
    expected_script = script_for_language(detected_language or language)
    if asr_backend == "stub":
        warnings.append(
            "No ASR available - ran with the deterministic stub transcript. "
            "Install whisper.cpp (or import an .srt) for real results."
        )

    progress("align", 0.5, "refining word timings")
    all_words = refine_words(flat_words(utterances), analysis)

    progress("windows", 0.56, "building sentence-aligned windows")
    windows = build_windows(utterances, SETTINGS.windows)
    if windows:
        # Snapping is cosmetic: it moves edges onto real edits so a clip does not
        # open mid-transition. When detection finds nothing (audio-only sources,
        # no keyframes) the windows pass through untouched.
        cuts = cuts_for(source.path, SETTINGS.scenes, source.duration)
        if cuts:
            windows = snap_windows(
                windows,
                utterances,
                cuts,
                SETTINGS.scenes.snap_tolerance_s,
                SETTINGS.windows.min_s,
                SETTINGS.windows.max_s,
            )
            progress("windows", 0.58, f"snapped to {len(cuts)} scene cuts")
    if not windows:
        warnings.append("No speech found above the window threshold.")
        empty = AnalysisResult(
            source=source,
            candidates=[],
            asr_backend=asr_backend,
            llm_backend="none",
            policy_version=policy.active().version,
            duration_s=0.0,
            language=normalise(detected_language or language),
            warnings=warnings,
        )
        db.save_analysis(empty)
        return empty

    if chat_path is None:
        chat_path = chat_path_for(source)
    chat = load_chat_rate(chat_path, source.duration)
    available = {"audio", "excitement", "speech", "hook_lexicon"}
    if chat is not None:
        available.add("chat")
    else:
        if chat_path is not None:
            # A file was there but nothing usable came out of it.
            warnings.append("Chat replay was empty or too sparse - chat weight redistributed.")
        else:
            warnings.append("No chat replay - chat weight redistributed to other signals.")

    progress("signals", 0.64, f"scoring {len(windows)} windows")
    raw: dict[str, list[float]] = {k: [] for k in ("audio", "excitement", "chat", "speech", "hook_lexicon")}
    features_list: list[WindowFeatures] = []
    words_by_window: list[list] = []
    word_index = WordIndex(all_words)
    for window in windows:
        words = word_index.between(window.start, window.end)
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
        gates = evaluate_gates(
            window, feats, words, SETTINGS.gates, source.duration, expected_script
        )
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
        policy_version=policy.active().version,
        duration_s=float(analysis.duration),
        reel_quality=reel_quality(selected),
        language=normalise(detected_language or language),
        warnings=warnings,
    )
    # A fresh run re-derives words, so manual caption pages no longer line up
    # with them. Hook overrides are text the user wrote and survive.
    db.clear_clip_edits(source.id, kind="captions")
    db.save_analysis(result)
    progress("done", 1.0, f"{len(selected)} clips from {len(scored)} windows")
    return result


def peaks_for(source_id: str, level: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    path = artifacts_for(source_id) / "peaks.npz"
    if not path.exists():
        raise FileNotFoundError("peaks not built yet")
    return load_peaks(path, level)


def trim_clip(
    source: SourceInfo,
    candidate_id: str,
    start: float | None = None,
    end: float | None = None,
    min_duration: float = 5.0,
) -> ClipCandidate:
    """Move a clip's in/out points and keep everything derived from them honest.

    Trimming is the one edit every clipper needs and almost none explain: change
    the timecode and the transcript, captions, gates and scorecard can all drift
    out of sync silently. Here the words are re-cut to the new span, the text is
    rebuilt from those words, and the gates are re-evaluated, so a trim that cuts
    a sentence in half *fails the structural gate* instead of shipping.
    """
    analysis = db.get_analysis(source.id)
    if analysis is None:
        raise FileNotFoundError("no analysis for this source")
    candidate = next((c for c in analysis.candidates if c.id == candidate_id), None)
    if candidate is None:
        raise KeyError("clip not found")

    upper = source.duration or candidate.end
    new_start = candidate.start if start is None else float(start)
    new_end = candidate.end if end is None else float(end)
    new_start = max(0.0, min(new_start, candidate.end - min_duration))
    new_end = max(new_start + min_duration, min(new_end, upper))
    moved = (
        abs(new_start - candidate.start) > 1e-6
        or abs(new_end - candidate.end) > 1e-6
    )

    words = [
        w.model_copy(
            update={
                "start": max(w.start, new_start),
                "end": min(w.end, new_end),
            }
        )
        for w in candidate.words
        if w.end > new_start + 1e-6 and w.start < new_end - 1e-6
    ]
    text = " ".join(w.text for w in words).strip()

    candidate.start = round(new_start, 3)
    candidate.end = round(new_end, 3)
    candidate.words = words
    candidate.text = text

    window = Window(
        start=candidate.start,
        end=candidate.end,
        text=text,
        word_probs=[w.prob for w in words],
        utterance_count=1 if words else 0,
        first_terminal=True,
        last_terminal=text.rstrip().endswith((".", "!", "?", "...")),
    )
    # Recompute the word-derived numbers from the trimmed transcript, but carry
    # over the measured speech coverage: re-deriving it here would report 100%
    # coverage for a stretch that was never checked, which is laundering.
    coverage = candidate.features.speech_coverage if candidate.features else 1.0
    features = window_features(
        text, candidate.start, candidate.end, [w.prob for w in words], None
    )
    features.speech_coverage = coverage
    candidate.features = features
    candidate.gates = [
        g for g in candidate.gates if g.id in {"not_shortlisted", "llm_critique"}
    ] + evaluate_gates(
        window, features, words, SETTINGS.gates, upper,
        script_for_language(analysis.language),
    )
    candidate.blocked = any(not g.passed and g.severity == "block" for g in candidate.gates)

    hook = candidate.llm.hook if candidate.llm else ""
    candidate.scorecard = build_scorecard(
        candidate, features, grounding_ratio(hook, text) if hook else 0.0
    )
    if moved:
        # Page timings were written against the old in/out points. Re-deriving
        # from the re-cut words is honest; carrying the edit over would drift.
        candidate.caption_pages = None
        db.clear_clip_edits(source.id, candidate_id, "captions")

    db.save_analysis(analysis)
    return candidate
