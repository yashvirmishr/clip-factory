"""Frame-accurate timecode maths shared by every editor export.

Every format an editor consumes is counted in frames, and every one of them
counts differently. Getting this wrong produces a handoff that looks right in a
text editor and lands 8 frames off in Premiere, so the arithmetic lives in one
place and the exporters are not allowed to do their own.

Drop-frame is deliberately not implemented. It only matters for 29.97/59.94
material longer than ~10 minutes, and a short is 15-90 seconds, where non-drop
timecode differs from wall clock by a few frames at most. Saying so is better
than a half-correct drop-frame implementation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    """A real frame rate plus the integer rate timecode counts in."""

    fps: float
    nominal: int

    @property
    def drop_frame(self) -> bool:
        return False


def rate_for(fps: float) -> Rate:
    """29.97 counts timecode at 30, 23.976 at 24, and so on."""
    safe = fps if fps and fps > 0.5 else 30.0
    return Rate(fps=round(safe, 4), nominal=max(1, int(round(safe))))


def frames_at(seconds: float, rate: Rate) -> int:
    """Nearest frame for a wall-clock time. Never negative."""
    return max(0, int(round(max(0.0, seconds) * rate.fps)))


def seconds_at(frames: int, rate: Rate) -> float:
    return max(0, frames) / rate.fps


def timecode(frames: int, rate: Rate, sep: str = ":") -> str:
    """HH:MM:SS:FF in non-drop-frame."""
    frames = max(0, int(frames))
    nominal = rate.nominal
    ff = frames % nominal
    total_seconds = frames // nominal
    ss = total_seconds % 60
    mm = (total_seconds // 60) % 60
    hh = total_seconds // 3600
    return f"{hh:02d}{sep}{mm:02d}{sep}{ss:02d}{sep}{ff:02d}"


def timecode_at(seconds: float, rate: Rate, sep: str = ":") -> str:
    return timecode(frames_at(seconds, rate), rate, sep)


def parse_timecode(value: str, rate: Rate) -> int:
    """Inverse of :func:`timecode`, used by tests and by round-trip checks."""
    parts = value.replace(";", ":").split(":")
    if len(parts) != 4:
        raise ValueError(f"not a timecode: {value!r}")
    hh, mm, ss, ff = (int(part) for part in parts)
    return ((hh * 60 + mm) * 60 + ss) * rate.nominal + ff
