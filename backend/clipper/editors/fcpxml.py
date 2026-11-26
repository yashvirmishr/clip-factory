"""FCPXML 1.10 export for Final Cut Pro X and DaVinci Resolve.

FCP7 XML (``xmeml``) still imports into Premiere and Resolve, but Final Cut Pro X
has only ever accepted FCPXML. It is a different document, not a relabelling:
resources are declared once at the top, the timeline is a spine of clips, and
every time is a rational number of seconds.

Two things that quietly break imports:

* time values must be reduced rationals with an ``s`` suffix - ``3000/30000s``
  is accepted, ``100/1000s`` everywhere is not always;
* an ``asset-clip``'s ``start`` is the in-point inside the asset, while
  ``offset`` is where it sits on the timeline. Swapping them gives a timeline
  that looks right and plays the wrong footage.
"""

from __future__ import annotations

from fractions import Fraction
from xml.sax.saxutils import escape

from .spec import ClipSpec


def _fps_fraction(fps: float) -> Fraction:
    """23.976 -> 24000/1001, 29.97 -> 30000/1001, 30 -> 30/1."""
    return Fraction(max(0.5, fps or 30.0)).limit_denominator(1001)


def _rational(seconds: float, fps: float) -> str:
    """Time snapped to a whole frame, as the reduced rational FCPXML wants."""
    rate = _fps_fraction(fps)
    frames = Fraction(max(0.0, seconds)) * rate
    snapped = Fraction(int(round(frames)), 1) if frames.denominator else frames
    value = snapped / rate
    return f"{value.numerator}/{value.denominator}s"


def _frame_duration(fps: float) -> str:
    value = 1 / _fps_fraction(fps)
    return f"{value.numerator}/{value.denominator}s"


def _format_name(spec: ClipSpec) -> str:
    height = spec.height or 1080
    width = spec.width or 1920
    short = min(height, width)
    base = {1080: "1080p", 720: "720p", 2160: "2160p"}.get(short)
    if base is None:
        base = f"{short}p"
    return f"FFVideoFormat{base}{int(round(spec.fps or 30.0))}"


def build(specs: list[ClipSpec], title: str = "Clip Factory reel") -> str:
    if not specs:
        raise ValueError("no clips to export")
    fps = specs[0].fps or 30.0
    rate = _frame_duration(fps)

    assets: list[str] = []
    clips: list[str] = []
    offset = 0.0
    seen: dict[str, str] = {}

    for index, spec in enumerate(specs, start=1):
        key = str(spec.source_path)
        if key not in seen:
            asset_id = f"r{index + 1}"
            seen[key] = asset_id
            assets.append(
                f'    <asset id="{asset_id}" name="{escape(spec.source_name)}" '
                f'start="0s" duration="{_rational(spec.source_duration, fps)}" '
                f'hasVideo="1" hasAudio="1" audioSources="1" audioChannels="2" '
                f'format="r1">\n'
                f'      <media-rep kind="original-media" src="{escape(spec.file_url())}"/>\n'
                f"    </asset>"
            )
        asset_id = seen[key]

        marker = (
            f'\n          <marker start="{_rational(0.0, fps)}" '
            f'duration="{rate}" value="{escape(spec.hook[:80])}"/>'
            if spec.hook
            else ""
        )
        note = (
            f"\n          <note>{escape(f'score {spec.score:.3f}')}</note>"
            if spec.score
            else ""
        )
        children = marker + note
        tail = "/>" if not children else f">{children}</asset-clip>"
        clips.append(
            f'        <asset-clip ref="{asset_id}" name="{escape(spec.name)}" '
            f'offset="{_rational(offset, fps)}" '
            f'start="{_rational(spec.start, fps)}" '
            f'duration="{_rational(spec.duration, fps)}"'
            f"{tail}"
        )
        offset += spec.duration

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE fcpxml>\n"
        '<fcpxml version="1.10">\n'
        "  <resources>\n"
        f'    <format id="r1" name="{_format_name(specs[0])}" '
        f'frameDuration="{rate}" width="{specs[0].width or 1920}" '
        f'height="{specs[0].height or 1080}"/>\n'
        + "\n".join(assets)
        + "\n  </resources>\n"
        "  <library>\n"
        f'    <event name="{escape(title)}">\n'
        f'      <project name="{escape(title)}">\n'
        f'        <sequence format="r1" duration="{_rational(offset, fps)}" '
        'tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">\n'
        "          <spine>\n"
        + "\n".join(clips)
        + "\n          </spine>\n"
        "        </sequence>\n"
        "      </project>\n"
        "    </event>\n"
        "  </library>\n"
        "</fcpxml>\n"
    )


def rational_for(seconds: float, fps: float) -> Fraction:
    """Test helper: the exact value a rational time string represents."""
    rate = _fps_fraction(fps)
    frames = Fraction(max(0.0, seconds)) * rate
    return Fraction(int(round(frames)), 1) / rate
