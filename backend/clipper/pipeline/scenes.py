"""Scene cuts, chapters and shot boundaries.

A clip that begins mid-transition looks broken even when the moment itself is
good, so boundaries are nudged onto real edits instead of arbitrary timestamps.

Detection decodes **keyframes only** (``-skip_frame nokey``). A two-hour VOD has
a few thousand keyframes rather than a few hundred thousand frames, which keeps
this a seconds-long step instead of a minutes-long one. The price is that cuts
are only located to the nearest keyframe, so snapping is limited to a sub-second
tolerance and is never allowed to decide *which* moments get clipped - the
transcript and the signals own that decision.

The pure functions here (parsing, snapping, chapters, shots) carry the logic and
are tested without touching ffmpeg.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import SETTINGS, SceneConfig

FFMPEG = "ffmpeg"

_PTS = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")
_SCORE = re.compile(r"scene_score\s*=\s*([0-9.]+)")


@dataclass(frozen=True)
class SceneCut:
    time: float
    score: float


def parse_cut_blocks(text: str) -> list[SceneCut]:
    """Parse ``metadata=print`` output into (time, score) pairs.

    ffmpeg prints a block per selected frame::

        frame:0    pts:0       pts_time:12.512
        lavfi.scene_score=0.412345

    The timestamp and the score arrive on separate lines, so they are paired by
    position rather than by regex order alone.
    """
    cuts: list[SceneCut] = []
    pending: float | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _PTS.search(line)
        if match:
            pending = float(match.group(1))
            continue
        match = _SCORE.search(line)
        if match and pending is not None:
            cuts.append(SceneCut(time=round(pending, 3), score=float(match.group(1))))
            pending = None
    return cuts


def dedupe_cuts(cuts: list[SceneCut], min_gap: float = 1.0) -> list[float]:
    """Collapse cuts that land on the same edit.

    Keyframe-only decoding reports several frames of a single cut; keep the
    strongest of each cluster instead of five timestamps two frames apart.
    """
    if not cuts:
        return []
    ordered = sorted(cuts, key=lambda c: c.time)
    clusters: list[list[SceneCut]] = [[ordered[0]]]
    for cut in ordered[1:]:
        if cut.time - clusters[-1][-1].time < min_gap:
            clusters[-1].append(cut)
        else:
            clusters.append([cut])
    return [round(max(cluster, key=lambda c: c.score).time, 3) for cluster in clusters]


def detect_cuts(
    path: str | Path,
    cfg: SceneConfig | None = None,
    timeout: int = 300,
    duration: float = 0.0,
) -> list[float]:
    """Scene cuts in seconds, ascending. Empty when the media has no video.

    Two passes, cheapest first:

    1. **keyframes only** - a streaming VOD has a ~2 s GOP, so this is a few
       thousand decodes instead of a few hundred thousand;
    2. **1 fps dense scan** - only when the first pass found nothing, and only on
       sources short enough to decode in bounded time. Files encoded locally
       often hold one keyframe for minutes of footage, and keyframe-only
       detection is then blind to every cut in them.
    """
    cfg = cfg or SETTINGS.scenes
    if not cfg.enabled or not Path(path).exists():
        return []

    fast = _scan(path, cfg, timeout, skip_keyframes=True)
    if fast:
        return fast
    if duration and duration > cfg.dense_max_s:
        return []
    # Sampled frames are a second apart, so a subject walking across frame scores
    # like an edit. Demand a bigger change and a wider gap to compensate.
    return _scan(
        path,
        SceneConfig(
            threshold=min(0.9, cfg.threshold * 1.6),
            min_gap_s=max(cfg.min_gap_s, 3.0),
            dense_max_s=cfg.dense_max_s,
        ),
        timeout,
        skip_keyframes=False,
    )


def _scan(
    path: str | Path,
    cfg: SceneConfig,
    timeout: int,
    *,
    skip_keyframes: bool,
) -> list[float]:
    command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostats"]
    if skip_keyframes:
        command += ["-skip_frame", "nokey"]
    command += [
        "-i", str(path),
        "-an", "-sn",
        "-vf", (
            ("" if skip_keyframes else "fps=1,")
            + f"scale=160:-2,select='gt(scene,{cfg.threshold:.3f})',"
            "metadata=print:file=-"
        ),
        # The null muxer must NOT write to "-": it shares the handle with
        # metadata=print and the two writers clobber each other, which made this
        # detector silently return nothing at all.
        "-f", "null", os.devnull,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return []
    return dedupe_cuts(parse_cut_blocks(result.stdout), cfg.min_gap_s)


def nearest_cut(time: float, cuts: list[float], tolerance: float) -> float | None:
    if not cuts:
        return None
    best = min(cuts, key=lambda cut: abs(cut - time))
    return best if abs(best - time) <= tolerance else None


@lru_cache(maxsize=8)
def _cached_cuts(
    path: str, mtime: float, threshold: float, min_gap: float, duration: float
) -> tuple[float, ...]:
    cfg = SceneConfig(threshold=threshold, min_gap_s=min_gap)
    return tuple(detect_cuts(path, cfg, duration=duration))


def cuts_for(
    path: str | Path,
    cfg: SceneConfig | None = None,
    duration: float = 0.0,
) -> list[float]:
    """Detect once per source; the detector decodes, so callers share the result."""
    cfg = cfg or SETTINGS.scenes
    resolved = Path(path).resolve()
    try:
        mtime = resolved.stat().st_mtime
    except OSError:
        return []
    return list(
        _cached_cuts(
            str(resolved), mtime, cfg.threshold, cfg.min_gap_s, round(duration, 1)
        )
    )


def snap_bounds(
    start: float,
    end: float,
    cuts: list[float],
    cfg: SceneConfig | None = None,
    min_duration: float = 8.0,
    max_duration: float = 90.0,
) -> tuple[float, float]:
    """Move a window's edges onto nearby cuts without breaking the duration budget.

    Only the outer edges move, and a move is rejected if it would push the clip
    outside ``min_duration..max_duration``. Snapping must never change what the
    clip is *about*, only where it starts and stops.
    """
    cfg = cfg or SETTINGS.scenes
    tolerance = cfg.snap_tolerance_s
    new_start, new_end = start, end

    cut = nearest_cut(start, cuts, tolerance)
    if cut is not None and cut < start and (end - cut) <= max_duration and (end - cut) >= min_duration:
        new_start = cut

    cut = nearest_cut(end, cuts, tolerance)
    if cut is not None and cut > end and (cut - new_start) <= max_duration:
        new_end = cut
    elif cut is not None and cut < end and (cut - new_start) >= min_duration:
        new_end = cut

    return round(new_start, 3), round(new_end, 3)


def shots_between(
    cuts: list[float],
    start: float,
    end: float,
    min_shot_s: float = 0.4,
) -> list[tuple[float, float]]:
    """Split ``start..end`` at the cuts inside it.

    Returns at least one span, so callers never special-case "no cuts found".
    Spans shorter than ``min_shot_s`` are folded into the previous one: a 3-frame
    flash cut is not a framing decision.
    """
    if end <= start:
        return [(start, end)]
    # Drop cuts that would create a sliver instead of moving a real cut's
    # position: a 4-frame flash is not a shot, and honouring it would drag the
    # boundary off the edit we actually found.
    boundaries = [start]
    for cut in cuts:
        if start + 0.05 < cut < end - 0.05 and cut - boundaries[-1] >= min_shot_s:
            boundaries.append(cut)
    if boundaries[-1] != start and end - boundaries[-1] < min_shot_s:
        boundaries.pop()
    boundaries.append(end)
    return list(zip(boundaries, boundaries[1:]))


def chapters(
    cuts: list[float],
    duration: float,
    target_s: float = 300.0,
) -> list[tuple[float, float]]:
    """Coarse chapters, used to spread picks across a long stream.

    Boundaries prefer a real cut near the target length and fall back to the
    grid when the footage is a single unbroken take (a podcast camera that never
    cuts, for instance).
    """
    if duration <= 0:
        return []
    if duration <= target_s:
        return [(0.0, duration)]

    edges = [0.0]
    target = target_s
    while target < duration - target_s * 0.5:
        cut = nearest_cut(target, cuts, target_s * 0.35)
        edge = cut if cut is not None else target
        if edge - edges[-1] > 20:
            edges.append(round(edge, 3))
        target = edge + target_s
    edges.append(round(duration, 3))
    return list(zip(edges, edges[1:]))
