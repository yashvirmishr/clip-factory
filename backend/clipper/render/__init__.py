"""Clip rendering: caption pages -> ASS -> a finished vertical MP4."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import SETTINGS
from ..domain import ClipCandidate, SourceInfo
from ..pipeline.caption import group_words
from .ass import get_preset, style_summary, write_ass
from .ffmpeg import FRAMINGS, RenderSpec, build_args, choose_encoder, ffprobe_duration


class RenderError(RuntimeError):
    pass


def renders_dir() -> Path:
    path = (SETTINGS.data_dir / "renders").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def render_clip(
    source: SourceInfo,
    candidate: ClipCandidate,
    preset_key: str = "hormozi",
    framing: str = "blur",
    force: bool = False,
    progress=None,
) -> dict:
    if framing not in FRAMINGS:
        framing = "blur"
    style = get_preset(preset_key)
    out = renders_dir() / f"{candidate.id}-{style.key}-{framing}.mp4"

    if out.exists() and out.stat().st_size > 10_000 and not force:
        return {
            "cached": True,
            "url": f"/api/renders/{out.name}",
            "filename": out.name,
            "duration": round(ffprobe_duration(out), 2),
            "style": style_summary(style),
            "framing": framing,
        }

    pages = group_words(candidate.words, SETTINGS.captions)
    if not pages:
        raise RenderError("this clip has no caption pages to burn")
    if progress:
        progress("captions", 0.15, f"{len(pages)} pages")

    work = renders_dir() / candidate.id
    ass_path = write_ass(
        pages,
        style,
        candidate.start,
        work / f"{style.key}.ass",
        SETTINGS.captions.max_chars_per_line,
        SETTINGS.captions.max_lines,
    )

    spec = RenderSpec(
        src=Path(source.path).resolve(),
        out=out.resolve(),
        start=candidate.start,
        duration=candidate.end - candidate.start,
        ass_name=ass_path.name,
        framing=framing,
        encoder=choose_encoder(),
    )
    if progress:
        progress("render", 0.35, f"{spec.encoder} · {framing}")

    result = subprocess.run(
        build_args(spec), cwd=str(work), capture_output=True, text=True, timeout=3600
    )
    if result.returncode != 0 and spec.encoder != "libx264":
        # A driver can disappear between the probe and the real run; a hardware
        # encoder is never worth failing a render over.
        spec.encoder = "libx264"
        result = subprocess.run(
            build_args(spec), cwd=str(work), capture_output=True, text=True, timeout=3600
        )
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed: {result.stderr.strip()[:600]}")
    if progress:
        progress("render", 0.9, "muxing")

    duration = ffprobe_duration(out)
    return {
        "cached": False,
        "url": f"/api/renders/{out.name}",
        "filename": out.name,
        "duration": round(duration, 2),
        "bytes": out.stat().st_size,
        "pages": len(pages),
        "style": style_summary(style),
        "framing": framing,
        "encoder": spec.encoder,
    }
