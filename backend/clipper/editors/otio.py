"""OpenTimelineIO export.

OTIO is the handoff that does not lie about age: it is JSON, it is what Resolve,
Premiere (via the adapter), and FilmCraft all read, and it references media by
URL instead of copying gigabytes.

The timeline is a single video track with the clips laid end to end - a rough cut
you can drag straight in - with the hook as a marker on each clip. Captions are
not represented as a track: OTIO has no subtitle primitive that NLEs honour, so
claiming otherwise would be a handoff that silently drops the captions. They ride
along as SRT sidecars in the same bundle.
"""

from __future__ import annotations

import json

from .spec import ClipSpec

OTIO_SCHEMA = "OTIO_SCHEMA"


def _time(value: float, rate: float) -> dict:
    return {OTIO_SCHEMA: "RationalTime.1", "value": float(value), "rate": float(rate)}


def _range(start_frames: int, duration_frames: int, rate: float) -> dict:
    return {
        OTIO_SCHEMA: "TimeRange.1",
        "start_time": _time(start_frames, rate),
        "duration": _time(duration_frames, rate),
    }


def _clip(spec: ClipSpec) -> dict:
    rate = spec.rate.fps
    markers = []
    if spec.hook:
        markers.append(
            {
                OTIO_SCHEMA: "Marker.1",
                "name": "hook",
                "color": "RED",
                "marked_range": _range(0, 1, rate),
                "metadata": {"clip_factory": {"hook": spec.hook}},
            }
        )
    return {
        OTIO_SCHEMA: "Clip.1",
        "name": spec.name,
        "media_reference": {
            OTIO_SCHEMA: "ExternalReference.1",
            "target_url": spec.file_url(),
            "available_range": _range(
                0, max(1, int(round(spec.source_duration * rate))), rate
            ),
            "metadata": {},
        },
        "source_range": _range(spec.in_frame, spec.duration_frames, rate),
        "markers": markers,
        "effects": [],
        "enabled": True,
        "metadata": {
            "clip_factory": {
                "clip_id": spec.id,
                "rank": spec.rank,
                "score": spec.score,
                "title": spec.title,
                "hook": spec.hook,
                "in_seconds": spec.start,
                "out_seconds": spec.end,
                "framing_knots": [list(knot) for knot in spec.crop],
                "caption_pages": len(spec.pages),
            }
        },
    }


def build(specs: list[ClipSpec], name: str = "Clip Factory reel") -> dict:
    rate = specs[0].rate.fps if specs else 30.0
    return {
        OTIO_SCHEMA: "Timeline.1",
        "name": name,
        "global_start_time": None,
        "metadata": {
            "clip_factory": {
                "clip_count": len(specs),
                "source": specs[0].source_path.as_posix() if specs else "",
            }
        },
        "tracks": {
            OTIO_SCHEMA: "Stack.1",
            "name": "tracks",
            "children": [
                {
                    OTIO_SCHEMA: "Track.1",
                    "name": "V1",
                    "kind": "Video",
                    "enabled": True,
                    "children": [_clip(spec) for spec in specs],
                    "markers": [],
                    "effects": [],
                    "metadata": {"clip_factory": {"rate": rate}},
                }
            ],
            "markers": [],
            "effects": [],
            "enabled": True,
            "metadata": {},
        },
    }


def dumps(specs: list[ClipSpec], name: str = "Clip Factory reel") -> str:
    return json.dumps(build(specs, name), indent=2, ensure_ascii=False)
