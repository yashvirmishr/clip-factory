"""EDL (CMX 3600) export.

The oldest and least glamorous format here, and the only one every NLE has read
continuously for thirty years. It is also the best fallback when an XML importer
chokes on a codec it does not recognise: an EDL carries no media at all, just
timecodes and a reel name, so nothing can go offline.

Reel name is ``AX`` (auxiliary source) which Premiere and Resolve both accept for
file-based media. Comments carry the clip name and hook because EDL has nowhere
else to put them.
"""

from __future__ import annotations

from .spec import ClipSpec
from .timecode import frames_at, timecode

TITLE = "CLIP FACTORY REEL"


def _line(event: int, spec: ClipSpec, record_in: int) -> list[str]:
    rate = spec.rate
    lines = [
        f"{event:03d}  AX       V     C        "
        f"{timecode(spec.in_frame, rate)} {timecode(spec.out_frame, rate)} "
        f"{timecode(record_in, rate)} {timecode(record_in + spec.duration_frames, rate)}",
        f"* FROM CLIP NAME: {spec.source_name}",
    ]
    if spec.hook:
        lines.append(f"* HOOK: {spec.hook[:120]}")
    if spec.crop:
        lines.append("* FRAMING: auto (crop follows subject per shot)")
    return lines


def build(specs: list[ClipSpec], title: str = TITLE) -> str:
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    record_in = 0
    for index, spec in enumerate(specs, start=1):
        lines.extend(_line(index, spec, record_in))
        lines.append("")
        record_in += spec.duration_frames
    return "\n".join(lines).rstrip() + "\n"


def record_length_frames(specs: list[ClipSpec]) -> int:
    return sum(spec.duration_frames for spec in specs)


def start_frame(spec: ClipSpec) -> int:
    return frames_at(spec.start, spec.rate)
