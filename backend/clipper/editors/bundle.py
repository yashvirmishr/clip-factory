"""The handoff bundle: one zip an editor can open without a manual.

The point of shipping four formats at once is that no single one is trustworthy
on every machine: OTIO is the clean modern path, FCP7 XML is what Premiere and
Resolve import without a plugin, EDL is the fallback that cannot go offline, and
SRT keeps the words editable. Whichever one the editor accepts, the timecodes
came from the same functions.

Media is **referenced**, never copied. A 2-hour VOD in a zip would be a mail
attachment nobody can send, and the editor already has the file.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .. import __version__
from . import edl, otio, srt, xmeml
from .spec import ClipSpec

READ_ME = """Clip Factory handoff
====================

Files in this bundle:

  reel.otio      OpenTimelineIO. Resolve, Premiere (with the OTIO adapter) and
                 FilmCraft import this directly.
  reel.xml       FCP7 XML (xmeml). Premiere and Resolve import this natively.
  reel.edl       CMX 3600. The fallback that works everywhere; carries no media.
  captions/*.srt Caption pages per clip, same timings as the burned-in version.
  manifest.json  Every clip's in/out, frames, hook, score and framing knots.
  render/        Optional: rendered 1080x1920 MP4s, if they were included.

Media is referenced by absolute path, not copied. If a clip opens offline, the
source file moved; relink to the same path and the cut stays intact.

Import order to try: reel.otio, then reel.xml, then reel.edl.
"""


def manifest(specs: list[ClipSpec], renders: list[str] | None = None) -> dict:
    return {
        "generator": f"clip-factory/{__version__}",
        "clip_count": len(specs),
        "total_duration": round(sum(spec.duration for spec in specs), 3),
        "source": {
            "path": specs[0].source_path.as_posix() if specs else "",
            "name": specs[0].source_name if specs else "",
            "fps": specs[0].fps if specs else 0,
            "width": specs[0].width if specs else 0,
            "height": specs[0].height if specs else 0,
            "duration": specs[0].source_duration if specs else 0,
        },
        "media_embedded": False,
        "clips": [
            {
                "id": spec.id,
                "rank": spec.rank,
                "name": spec.name,
                "title": spec.title,
                "hook": spec.hook,
                "score": spec.score,
                "in": spec.start,
                "out": spec.end,
                "in_frame": spec.in_frame,
                "out_frame": spec.out_frame,
                "duration": round(spec.duration, 3),
                "timecode": {
                    "in": spec.rate and _tc(spec.in_frame, spec),
                    "out": _tc(spec.out_frame, spec),
                },
                "caption_pages": len(spec.pages),
                "framing_knots": [list(knot) for knot in spec.crop],
                "srt": f"captions/{spec.id}.srt",
            }
            for spec in specs
        ],
        "renders": renders or [],
    }


def _tc(frames: int, spec: ClipSpec) -> str:
    from .timecode import timecode

    return timecode(frames, spec.rate)


def files(
    specs: list[ClipSpec],
    renders: list[Path] | None = None,
    title: str = "Clip Factory reel",
) -> dict[str, bytes]:
    """Every bundle member as bytes, so the caller can zip or serve individually."""
    out: dict[str, bytes] = {
        "reel.otio": otio.dumps(specs, title).encode("utf-8"),
        "reel.xml": xmeml.build(specs, title).encode("utf-8"),
        "reel.edl": edl.build(specs).encode("utf-8"),
        "README.txt": READ_ME.encode("utf-8"),
    }
    for spec in specs:
        out[f"captions/{spec.id}.srt"] = srt.build(spec).encode("utf-8")

    render_names: list[str] = []
    for path in renders or []:
        if path.exists():
            out[f"render/{path.name}"] = path.read_bytes()
            render_names.append(path.name)

    out["manifest.json"] = json.dumps(
        manifest(specs, render_names), indent=2, ensure_ascii=False
    ).encode("utf-8")
    return out


def zip_bytes(members: dict[str, bytes], title: str = "clip-factory-reel") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def safe_name(title: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in title).strip("-")
    return cleaned or "clip-factory-reel"
