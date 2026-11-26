"""Editor handoff: the same clip decision expressed for an NLE.

Four formats, one ``ClipSpec`` per clip, one set of timecode functions. The
formats exist because no single one is accepted everywhere:

* ``otio``    - modern, JSON, what FilmCraft and Resolve read
* ``fcpxml``  - FCPXML 1.10, the only timeline Final Cut Pro X accepts
* ``fcp7xml`` - xmeml, native in Premiere and Resolve (``xmeml`` also works)
* ``edl``     - CMX 3600, the universal fallback that cannot go offline
* ``srt``     - caption pages, so burned-in text stays editable

``bundle`` combines all of them plus a manifest into a zip.
"""

from __future__ import annotations

from ..domain import AnalysisResult, SourceInfo
from . import bundle, edl, fcpxml, otio, srt, vtt, xmeml
from .spec import ClipSpec, spec_for, specs_for
from .timecode import Rate, frames_at, parse_timecode, rate_for, timecode

FORMATS = ("otio", "fcpxml", "fcp7xml", "edl", "srt", "bundle")

__all__ = [
    "ClipSpec",
    "FORMATS",
    "Rate",
    "bundle",
    "build_export",
    "edl",
    "fcpxml",
    "frames_at",
    "otio",
    "parse_timecode",
    "rate_for",
    "spec_for",
    "specs_for",
    "srt",
    "vtt",
    "timecode",
    "xmeml",
]


def build_export(
    source: SourceInfo,
    analysis: AnalysisResult,
    fmt: str = "otio",
    title: str = "Clip Factory reel",
) -> tuple[str, str, bytes]:
    """``(filename, media_type, payload)`` for one export format."""
    specs = specs_for(source, analysis)
    if not specs:
        raise ValueError("this source has no selected clips to export")

    if fmt == "otio":
        return f"{bundle.safe_name(title)}.otio", "application/json", otio.dumps(specs, title).encode("utf-8")
    if fmt == "fcpxml":
        return (
            f"{bundle.safe_name(title)}.fcpxml",
            "application/xml",
            fcpxml.build(specs, title).encode("utf-8"),
        )
    if fmt in {"fcp7xml", "xmeml"}:
        return (
            f"{bundle.safe_name(title)}-fcp7.xml",
            "application/xml",
            xmeml.build(specs, title).encode("utf-8"),
        )
    if fmt == "edl":
        return f"{bundle.safe_name(title)}.edl", "text/plain", edl.build(specs).encode("utf-8")
    if fmt == "srt":
        merged = "\n".join(srt.build(spec) for spec in specs)
        return f"{bundle.safe_name(title)}.srt", "text/plain", merged.encode("utf-8")
    if fmt == "bundle":
        members = bundle.files(specs, title=title)
        payload = bundle.zip_bytes(members, title)
        return f"{bundle.safe_name(title)}.zip", "application/zip", payload
    raise ValueError(f"unknown export format: {fmt}")
