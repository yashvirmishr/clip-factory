"""ASS caption generation with karaoke word highlighting.

libass is the only caption renderer that gets word-accurate highlighting without
rasterising frames ourselves, and it is already present in the bundled ffmpeg
build. Two details that silently corrupt output if you get them wrong:

* ``{`` and ``}`` in caption text are override blocks, not characters
* comma is a field separator in ``Dialogue`` lines, so text is always last
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..pipeline.caption import CaptionPage

RES_X = 1080
RES_Y = 1920


@dataclass(frozen=True)
class CaptionStyle:
    """One preset. Colours are ASS ``&HAABBGGRR`` (alpha, B, G, R)."""

    key: str
    label: str
    font: str
    size: int
    primary: str = "&H001A5CFF"  # spoken word (tungsten)
    secondary: str = "&H00FFFFFF"  # not yet spoken
    outline: str = "&H00000000"
    back: str = "&H80000000"
    bold: int = -1
    outline_width: float = 7.0
    shadow: float = 2.0
    alignment: int = 2  # bottom centre
    margin_v: int = 300
    margin_h: int = 90
    uppercase: bool = True
    karaoke: str = "k"  # "k" instant, "kf" sweep, "none"


PRESETS: dict[str, CaptionStyle] = {
    "hormozi": CaptionStyle(
        key="hormozi", label="Hormozi", font="Arial Black", size=104,
        primary="&H001A5CFF", secondary="&H00FFFFFF", outline_width=8.0,
    ),
    "box": CaptionStyle(
        key="box", label="Box", font="Arial Black", size=88,
        primary="&H001A5CFF", secondary="&H00FFFFFF", outline_width=0.0,
        shadow=0.0, back="&HCC000000",
    ),
    "karaoke": CaptionStyle(
        key="karaoke", label="Karaoke", font="Arial Black", size=92,
        primary="&H002DD4A7", secondary="&H00EDE8E1", karaoke="kf",
    ),
    "minimal": CaptionStyle(
        key="minimal", label="Minimal", font="Segoe UI Semibold", size=74,
        primary="&H001A5CFF", secondary="&H00FFFFFF", outline_width=3.0,
        shadow=0.0, uppercase=False, margin_v=240,
    ),
    "landscape": CaptionStyle(
        key="landscape", label="Landscape", font="Segoe UI Semibold", size=62,
        primary="&H001A5CFF", secondary="&H00F5F5F5", outline_width=3.5,
        uppercase=False, alignment=2, margin_v=140,
    ),
}


def get_preset(key: str) -> CaptionStyle:
    return PRESETS.get(key, PRESETS["hormozi"])


def escape_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_cs = int(round(seconds * 100))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _wrap(words: list[str], max_chars: int, max_lines: int) -> list[list[str]]:
    lines: list[list[str]] = [[]]
    length = 0
    for word in words:
        if lines[-1] and length + 1 + len(word) > max_chars:
            if len(lines) >= max_lines:
                lines[-1].append(word)
                length += 1 + len(word)
                continue
            lines.append([word])
            length = len(word)
        else:
            lines[-1].append(word)
            length = len(word) if not length else length + 1 + len(word)
    return lines


def build_ass_document(
    pages: list[CaptionPage],
    style: CaptionStyle,
    clip_start: float,
    max_chars_per_line: int = 22,
    max_lines: int = 2,
) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {RES_X}
PlayResY: {RES_Y}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clip,{style.font},{style.size},{style.primary},{style.secondary},{style.outline},{style.back},{style.bold},0,0,0,100,100,0,0,{1 if style.outline_width else 3},{style.outline_width},{style.shadow},{style.alignment},{style.margin_h},{style.margin_h},{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    for page in pages:
        start = page.start - clip_start
        end = page.end - clip_start
        if end <= 0:
            continue
        start = max(0.0, start)
        words = [w.text.upper() if style.uppercase else w.text for w in page.words]
        if not words:
            continue
        lines = _wrap(words, max_chars_per_line, max_lines)

        chunks: list[str] = []
        index = 0
        for line_index, line in enumerate(lines):
            if line_index:
                chunks.append("\\N")
            for word in line:
                if index < len(page.words):
                    word_duration = max(0.02, page.words[index].end - page.words[index].start)
                else:
                    word_duration = 0.2
                centiseconds = max(1, int(round(word_duration * 100)))
                prefix = f"{{\\{style.karaoke}{centiseconds}}}" if style.karaoke != "none" else ""
                chunks.append(f"{prefix}{escape_text(word)} ")
                index += 1

        text = "".join(chunks).rstrip()
        events.append(
            f"Dialogue: 0,{_format_time(start)},{_format_time(end)},Clip,,0,0,0,,{{\\fad(60,80)}}{text}"
        )

    return header + "\n".join(events) + "\n"


def write_ass(
    pages: list[CaptionPage],
    style: CaptionStyle,
    clip_start: float,
    target: Path,
    max_chars_per_line: int = 22,
    max_lines: int = 2,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        build_ass_document(pages, style, clip_start, max_chars_per_line, max_lines),
        "utf-8",
    )
    return target


def style_summary(style: CaptionStyle) -> dict:
    return {
        "key": style.key,
        "label": style.label,
        "font": style.font,
        "size": style.size,
        "karaoke": style.karaoke,
        "uppercase": style.uppercase,
    }
