"""Bake the reel into finished files.

The handoff formats describe an edit; this one performs it. Every ranked clip is
rendered with the chosen caption preset and framing, then the completed MP4s,
their caption sidecars and a manifest are written to one folder.

The details that matter:

* the folder is stable per source, so baking twice replaces the previous bake
  instead of filling a data directory with orphans;
* the renders themselves are reused from the render cache - a bake is not a
  second, slower renderer - and hard-linked where the filesystem allows it so a
  ten-clip reel does not double its disk use;
* one clip failing to render does not lose the other nine: the failure is
  recorded in the manifest and the job keeps going.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from ..config import SETTINGS
from ..domain import AnalysisResult, SourceInfo
from ..render import RenderError, render_clip
from .spec import specs_for
from . import srt as srt_editor


def bakes_root() -> Path:
    path = (SETTINGS.data_dir / "exports").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def bake_dir(source: SourceInfo) -> Path:
    return bakes_root() / source.id


def _link_or_copy(src: Path, dest: Path) -> None:
    """Hard-link when possible; copy otherwise. Never leave a half file."""
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
        return
    except OSError:
        pass
    shutil.copy2(src, dest)


def _safe(name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in " -_" else "" for char in name).strip()
    return (cleaned or "clip")[:80]


def bake_reel(
    source: SourceInfo,
    analysis: AnalysisResult,
    preset: str = "hormozi",
    framing: str = "auto",
    approved_only: bool = False,
    approved: set[str] | None = None,
    progress=None,
) -> dict:
    """Render every selected clip and collect the results in one folder."""
    specs = specs_for(source, analysis)
    if approved_only:
        keep = approved or set()
        specs = [spec for spec in specs if spec.id in keep]
    if not specs:
        raise ValueError("no clips to bake - approve a clip or clear the filter")

    folder = bake_dir(source)
    if folder.exists():
        # A previous bake is replaced wholesale: stale MP4s in an export folder
        # are worse than no export at all.
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    captions = folder / "captions"
    captions.mkdir(exist_ok=True)

    by_id = {candidate.id: candidate for candidate in analysis.candidates}
    total = len(specs)
    clips: list[dict] = []

    for index, spec in enumerate(specs):
        candidate = by_id.get(spec.id)
        name = f"{index + 1:02d} {_safe(spec.name)}"
        entry: dict = {
            "id": spec.id,
            "rank": spec.rank,
            "name": name,
            "start": spec.start,
            "end": spec.end,
            "duration": round(spec.duration, 3),
        }
        if candidate is None:
            entry["error"] = "clip no longer exists in this analysis"
            clips.append(entry)
            continue

        def report(stage: str, pct: float, detail: str, _index: int = index, _name: str = name) -> None:
            if not progress:
                return
            overall = (_index + max(0.0, min(1.0, pct))) / total
            progress("render", overall, f"clip {_index + 1}/{total} · {_name} · {detail or stage}")

        try:
            result = render_clip(
                source,
                candidate,
                preset_key=preset,
                framing=framing,
                force=False,
                progress=report,
            )
        except (RenderError, OSError, ValueError) as exc:
            entry["error"] = str(exc)[:300]
            clips.append(entry)
            continue

        rendered = Path(SETTINGS.data_dir / "renders" / result["filename"])
        target = folder / f"{name}.mp4"
        try:
            _link_or_copy(rendered, target)
            entry["file"] = target.name
        except OSError as exc:
            # The render exists even when it cannot be copied; point at the cache
            # rather than pretending the clip was baked.
            entry["file"] = ""
            entry["render_url"] = result["url"]
            entry["copy_error"] = str(exc)[:200]
        entry["cached"] = bool(result.get("cached"))
        entry["framing"] = result.get("framing")
        entry["style"] = result.get("style")

        sidecar = captions / f"{name}.srt"
        sidecar.write_text(srt_editor.build(spec), "utf-8")
        entry["captions"] = f"captions/{sidecar.name}"
        clips.append(entry)

    baked = [clip for clip in clips if clip.get("file")]
    manifest = {
        "source": {"id": source.id, "name": source.name, "path": source.path},
        "created_at": time.time(),
        "preset": preset,
        "framing": framing,
        "approved_only": approved_only,
        "clip_count": len(clips),
        "baked": len(baked),
        "failed": len(clips) - len(baked),
        "clips": clips,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    (folder / "README.txt").write_text(_readme(source, manifest), "utf-8")

    if progress:
        progress("done", 1.0, f"{len(baked)}/{len(clips)} clips in {folder.name}")
    return {
        "folder": str(folder),
        "clip_count": len(clips),
        "baked": len(baked),
        "failed": len(clips) - len(baked),
        "manifest": str(folder / "manifest.json"),
        "clips": clips,
    }


def _readme(source: SourceInfo, manifest: dict) -> str:
    lines = [
        f"Baked reel for {source.name}",
        "",
        f"{manifest['baked']} of {manifest['clip_count']} clips rendered at 1080x1920,",
        f"caption preset '{manifest['preset']}', framing '{manifest['framing']}'.",
        "",
        "Files:",
        "  01 ... .mp4   One finished vertical clip, captions burned in.",
        "  captions/      The same caption pages as SRT sidecars.",
        "  manifest.json  Per-clip in/out, style, framing and any failure.",
        "",
        "Failures are listed in manifest.json; re-bake after fixing them rather",
        "than deleting individual files, so the folder always matches the reel.",
    ]
    return "\n".join(lines) + "\n"
