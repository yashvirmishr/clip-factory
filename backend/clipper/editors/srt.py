"""SRT sidecar captions.

Burned captions are furniture: once they are in the pixels they cannot be
retypeset, retimed or translated. Every clip handed to an editor also gets its
pages as SRT so the words stay editable - the same ``ClipSpec.pages`` the
renderer burns, converted through one timing function so the two cannot disagree.
"""

from __future__ import annotations

from .spec import ClipSpec


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build(spec: ClipSpec) -> str:
    blocks: list[str] = []
    for index, (start, end, text) in enumerate(spec.page_spans(), start=1):
        body = " ".join(text.split())
        if not body:
            continue
        blocks.append(f"{index}\n{_timestamp(start)} --> {_timestamp(end)}\n{body}\n")
    return "\n".join(blocks)


def build_flat(spec: ClipSpec) -> str:
    """One caption per sentence-ish line, for editors that dislike many cues."""
    spans = spec.page_spans()
    if not spans:
        return ""
    merged: list[tuple[float, float, list[str]]] = []
    for start, end, text in spans:
        if merged and start - merged[-1][1] < 0.6:
            merged[-1] = (merged[-1][0], end, merged[-1][2] + [text])
        else:
            merged.append((start, end, [text]))
    blocks = []
    for index, (start, end, parts) in enumerate(merged, start=1):
        body = " ".join(" ".join(parts).split())
        blocks.append(f"{index}\n{_timestamp(start)} --> {_timestamp(end)}\n{body}\n")
    return "\n".join(blocks)
