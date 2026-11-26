"""WebVTT sidecar captions.

Same timing source as the SRT exporter and the burned-in pages, so a file
downloaded from the app matches what the render shows. VTT differs from SRT in
two ways that matter here: milliseconds use a dot, and the file needs a header.
"""

from __future__ import annotations

from .spec import ClipSpec


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def build(spec: ClipSpec) -> str:
    blocks: list[str] = ["WEBVTT", ""]
    for start, end, text in spec.page_spans():
        body = " ".join(text.split())
        if not body:
            continue
        blocks.append(f"{_timestamp(start)} --> {_timestamp(end)}")
        blocks.append(body)
        blocks.append("")
    return "\n".join(blocks)
