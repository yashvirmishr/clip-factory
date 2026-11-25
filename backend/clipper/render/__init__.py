"""Clip rendering: caption pages -> ASS -> a finished vertical MP4."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import SETTINGS
from ..domain import ClipCandidate, SourceInfo, stable_id
from ..pipeline.caption import pages_for
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
    from ..pipeline.framing import plan_for_clip
    from ..pipeline.scenes import cuts_for

    if framing not in FRAMINGS:
        framing = "blur"
    style = get_preset(preset_key)

    # Resolve "auto" before naming the file: a failed sampling pass falls back to
    # a centred crop, and the filename must not claim otherwise.
    plan = None
    if framing == "auto":
        if progress:
            progress("framing", 0.12, "finding the subject")
        plan = plan_for_clip(source, candidate, cuts_for(source.path, None, source.duration))
        if plan is None:
            framing = "crop"

    pages = pages_for(candidate, SETTINGS.captions)
    if not pages:
        raise RenderError("this clip has no caption pages to burn")

    # Captions are part of the picture, so they are part of the cache key. A
    # manual edit must never come back as a cached render of the old words.
    digest = stable_id(*(page.model_dump_json() for page in pages))
    out = renders_dir() / f"{candidate.id}-{style.key}-{framing}-{digest}.mp4"

    if out.exists() and out.stat().st_size > 10_000 and not force:
        return {
            "cached": True,
            "url": f"/api/renders/{out.name}",
            "filename": out.name,
            "duration": round(ffprobe_duration(out), 2),
            "style": style_summary(style),
            "framing": framing,
            "crop": plan.summary() if plan else None,
        }

    if progress:
        progress("captions", 0.18, f"{len(pages)} pages")

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
        crop_w=plan.crop_w if plan else 0,
        crop_expr=plan.expression() if plan else "",
    )
    if progress:
        detail = f"{spec.encoder} · {framing}"
        if plan:
            detail += f" · {len(plan.knots)} knot crop"
        progress("render", 0.35, detail)

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
        "crop": plan.summary() if plan else None,
    }
