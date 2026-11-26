"""Subject-aware vertical framing.

Real clippers track faces. Bundling a face model (YuNet/ONNX, ~24 ms/frame plus a
runtime) is the wrong trade for this build, so "where is the subject" comes from
two cheap and explainable signals measured on a 96x54 grid:

* **motion** - frame-to-frame change per column. Faces, hands and gameplay
  action all move; a static wall does not.
* **skin density** - per-column share of skin-toned pixels, which keeps a
  talking head centred even while it is still.

The result is a *virtual camera*: one crop centre per shot, panned linearly
between shots. This is deliberate. Following the subject every frame reads as a
handheld camera and wobbles on every gesture; one position locked for the whole
clip ignores a cut to a different subject. One decision per shot is what an
editor would do.

The planner and the renderer share one geometry function (``CropPlan.at``), so
what is measured is exactly what gets displayed - drift between those two is how
"smart" reframing silently ships black bars.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..config import SETTINGS, FramingConfig
from ..domain import ClipCandidate, SourceInfo

FFMPEG = "ffmpeg"


@dataclass(frozen=True)
class CropPlan:
    """A piecewise-linear virtual camera path, in source pixels."""

    src_w: int
    src_h: int
    crop_w: int
    knots: tuple[tuple[float, float], ...]
    confidence: float = 0.0
    method: str = "activity"

    def at(self, time: float) -> float:
        """Crop left edge at ``time`` (clip-relative seconds)."""
        if not self.knots:
            return 0.0
        times = np.array([k[0] for k in self.knots], dtype=float)
        xs = np.array([k[1] for k in self.knots], dtype=float)
        return float(np.interp(time, times, xs))

    @property
    def maximum_x(self) -> int:
        return max(0, self.src_w - self.crop_w)

    def expression(self) -> str:
        """ffmpeg ``crop`` x expression - evaluated per frame against ``t``."""
        if not self.knots:
            return str(self.maximum_x // 2)
        if len(self.knots) == 1:
            return f"{self.knots[0][1]:.0f}"
        expr = f"{self.knots[-1][1]:.0f}"
        for (t0, x0), (t1, x1) in reversed(list(zip(self.knots, self.knots[1:]))):
            span = max(t1 - t0, 1e-3)
            ramp = f"{x0:.0f}+({x1 - x0:.0f})*(t-{t0:.3f})/{span:.3f}"
            expr = f"if(lt(t,{t1:.3f}),{ramp},{expr})"
        return expr

    def summary(self) -> dict:
        return {
            "method": self.method,
            "crop_w": self.crop_w,
            "knots": [[round(t, 2), round(x, 1)] for t, x in self.knots],
            "confidence": round(self.confidence, 3),
        }


def crop_width_for(src_w: int, src_h: int, out_w: int = 1080, out_h: int = 1920) -> int:
    """Width of the tallest 9:16 column that fits inside the source, in pixels."""
    if src_w <= 0 or src_h <= 0:
        return 0
    width = int(round(src_h * (out_w / out_h)))
    width = min(width, src_w)
    return max(2, width - (width % 2))


def _norm(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    values = values - float(values.min())
    peak = float(values.max())
    if peak <= 1e-9:
        return np.zeros_like(values)
    return values / peak


def frame_interest(frames: np.ndarray, cfg: FramingConfig | None = None) -> np.ndarray:
    """Per-frame, per-column interest, shape ``(n, w)`` in 0..1.

    Normalisation is global across the clip, so a quiet shot and a loud shot are
    comparable - otherwise every shot would renormalise to fill 0..1 and the
    camera would jump to whichever noise happened to peak.
    """
    cfg = cfg or SETTINGS.framing
    if frames.size == 0:
        return np.zeros((0, 1), dtype=float)
    if frames.ndim == 3:
        frames = frames[None, ...]

    count, _, width, _ = frames.shape
    motion = np.zeros((count, width), dtype=float)
    if count > 1:
        delta = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=3)
        motion[1:] = delta.mean(axis=1)

    pixels = frames.astype(np.int16)
    red, green, blue = pixels[..., 0], pixels[..., 1], pixels[..., 2]
    skin_mask = (
        (red > 95) & (green > 40) & (blue > 20)
        & (red > green) & (red > blue)
        & ((red - green) > 15) & (np.abs(red - blue) > 15)
    )
    skin = skin_mask.mean(axis=1).astype(float)

    return cfg.motion_weight * _norm(motion) + cfg.skin_weight * _norm(skin)


def best_center(interest: np.ndarray, crop_fraction: float) -> float:
    """Centre (0..1) of the window of ``crop_fraction`` width with most interest."""
    cols = len(interest)
    if cols == 0:
        return 0.5
    width = max(1, min(cols, int(round(crop_fraction * cols))))
    if width >= cols:
        return 0.5
    cumulative = np.concatenate(([0.0], np.cumsum(np.asarray(interest, dtype=float))))
    sums = cumulative[width:] - cumulative[:-width]
    if float(sums.max()) <= 1e-9:
        return 0.5
    start = int(np.argmax(sums))
    return (start + width / 2) / cols


def build_plan(
    times: list[float],
    interest: np.ndarray,
    shots: list[tuple[float, float]],
    src_w: int,
    src_h: int,
    clip_start: float,
    out_w: int = 1080,
    out_h: int = 1920,
) -> CropPlan | None:
    """One crop centre per shot, panned between shots.

    ``times`` are absolute seconds, ``interest`` is ``(len(times), w)``, and
    ``shots`` are absolute spans. Knots are emitted in clip-relative time because
    the renderer's ``t`` starts at zero.
    """
    crop_w = crop_width_for(src_w, src_h, out_w, out_h)
    if crop_w <= 0 or not shots or len(times) == 0 or interest.size == 0:
        return None

    time_values = np.asarray(times, dtype=float)
    fraction = min(1.0, crop_w / max(1, src_w))
    maximum_x = max(0, src_w - crop_w)

    knots: list[tuple[float, float]] = []
    confidence = 0.0
    for shot_start, shot_end in shots:
        rows = (time_values >= shot_start - 1e-6) & (time_values < shot_end + 1e-6)
        profile = interest[rows].mean(axis=0) if rows.any() else interest.mean(axis=0)
        centre = best_center(profile, fraction)
        confidence = max(confidence, min(1.0, abs(centre - 0.5) * 2))
        x = float(np.clip(centre * src_w - crop_w / 2, 0, maximum_x))
        x = round(x / 2) * 2  # even pixel keeps chroma siting happy
        knots.append((max(0.0, shot_start - clip_start), min(x, maximum_x)))

    if not knots:
        return None
    # The camera must exist from t=0 and stay defined to the last frame.
    if knots[0][0] > 0:
        knots.insert(0, (0.0, knots[0][1]))
    last_time = max(0.0, shots[-1][1] - clip_start)
    if knots[-1][0] < last_time:
        knots.append((last_time, knots[-1][1]))

    # A pan longer than the clip is worse than no pan: drop interior knots that
    # would not move the camera, but always keep the endpoint so the path is
    # explicitly defined to the last frame.
    if len(knots) == 1:
        deduped = knots
    else:
        deduped = [knots[0]]
        for knot in knots[1:-1]:
            if abs(knot[1] - deduped[-1][1]) >= 1.0:
                deduped.append(knot)
        deduped.append(knots[-1])

    if len(deduped) > 1:
        xs = [x for _, x in deduped]
        if max(xs) - min(xs) < 1.0:
            deduped = [(0.0, deduped[0][1])]

    return CropPlan(
        src_w=src_w,
        src_h=src_h,
        crop_w=crop_w,
        knots=tuple(deduped),
        confidence=round(confidence, 3),
    )


def simplify_knots(
    knots: list[tuple[float, float]],
    clip_end: float,
    deadband: float = 8.0,
    max_knots: int = 24,
) -> list[tuple[float, float]]:
    """Drop knots that would not visibly move the camera, and cap the count.

    A tracked face wobbles by a few pixels every frame. Panning to each of those
    reads as a shaky camera, so anything inside the deadband is discarded and
    the path stays one deliberate move per real change of position.
    """
    ordered = sorted(knots, key=lambda knot: knot[0])
    if not ordered:
        return []
    kept: list[tuple[float, float]] = [ordered[0]]
    for when, x in ordered[1:]:
        if abs(x - kept[-1][1]) >= deadband:
            kept.append((when, x))
    # The camera must be defined to the last frame even when nothing moved.
    if kept[-1][0] < clip_end:
        if abs(kept[-1][1] - ordered[-1][1]) >= deadband:
            kept.append((clip_end, ordered[-1][1]))
        else:
            kept.append((clip_end, kept[-1][1]))
    if max_knots > 1 and len(kept) > max_knots:
        stride = (len(kept) - 1) / (max_knots - 1)
        picked = [kept[int(round(index * stride))] for index in range(max_knots)]
        kept = picked
    if kept[0][0] > 0:
        kept.insert(0, (0.0, kept[0][1]))
    return kept


def plan_from_detections(
    times: list[float],
    detections: list[list],
    shots: list[tuple[float, float]],
    src_w: int,
    src_h: int,
    clip_start: float,
    out_w: int = 1080,
    out_h: int = 1920,
    detect_fps: float = 4.0,
    deadband: float = 8.0,
    max_knots: int = 24,
) -> "CropPlan | None":
    """A crop path from detected faces, one position per shot.

    Kept free of OpenCV on purpose: the detector is the only part that needs the
    optional package, so the maths here is testable with plain boxes.
    """
    from . import faces as facemod

    crop_w = crop_width_for(src_w, src_h, out_w, out_h)
    if crop_w <= 0 or not shots or not times or not detections:
        return None
    tracks = facemod.track(detections, times, fps=detect_fps)
    if not tracks:
        return None

    maximum_x = max(0, src_w - crop_w)
    confidence = 0.0
    knots: list[tuple[float, float]] = []
    for shot_start, shot_end in shots:
        track, _reason = facemod.choose_subject(
            tracks, shot_start, shot_end, crop_w, float(src_w)
        )
        if track is None:
            continue
        inside = [
            (when, box)
            for when, box in zip(track.times, track.boxes)
            if shot_start - 1e-6 <= when <= shot_end + 1e-6
        ] or list(zip(track.times, track.boxes))
        if not inside:
            continue
        for when, box in inside:
            left = float(np.clip(box.cx - crop_w / 2.0, 0, maximum_x))
            left = round(left / 2) * 2
            knots.append((max(0.0, when - clip_start), left))
        spread = max(box.cx for _when, box in inside) - min(box.cx for _when, box in inside)
        confidence = max(confidence, min(1.0, len(inside) / 4.0) * min(1.0, 1.0 - spread / max(1.0, src_w)))

    if not knots:
        return None
    clip_end = max(0.0, shots[-1][1] - clip_start)
    kept = simplify_knots(knots, clip_end, deadband, max_knots)
    return CropPlan(
        src_w=src_w,
        src_h=src_h,
        crop_w=crop_w,
        knots=tuple((round(t, 3), float(x)) for t, x in kept),
        confidence=round(confidence, 3),
        method="faces",
    )


def _frame_times(count: int, start: float, fps: float) -> list[float]:
    return [round(start + index / max(fps, 1e-6), 3) for index in range(count)]


def sample_frames(
    path: str | Path,
    start: float,
    duration: float,
    cfg: FramingConfig | None = None,
    timeout: int = 300,
) -> tuple[list[float], np.ndarray]:
    """Decode a coarse grid of frames.

    Squashing the aspect is fine here: only which *columns* the subject occupies
    matters, not its shape.
    """
    cfg = cfg or SETTINGS.framing
    if duration <= 0:
        return [], np.zeros((0, 0, 0, 3), dtype=np.uint8)
    grid_w, grid_h = cfg.grid_width, cfg.grid_height
    command = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostats",
        "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}",
        "-i", str(path),
        "-an", "-sn",
        "-vf", f"fps={cfg.sample_fps},scale={grid_w}:{grid_h}",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return [], np.zeros((0, 0, 0, 3), dtype=np.uint8)
    frame_size = grid_w * grid_h * 3
    usable = (len(result.stdout) // frame_size) * frame_size
    if usable <= 0:
        return [], np.zeros((0, 0, 0, 3), dtype=np.uint8)
    frames = np.frombuffer(result.stdout[:usable], dtype=np.uint8)
    frames = frames.reshape(-1, grid_h, grid_w, 3)
    return _frame_times(len(frames), start, cfg.sample_fps), frames


@lru_cache(maxsize=8)
def _cached_plan(
    path: str,
    mtime: float,
    start: float,
    end: float,
    src_w: int,
    src_h: int,
    shots: tuple[tuple[float, float], ...],
    grid: tuple[int, int],
    fps: float,
) -> CropPlan | None:
    cfg = FramingConfig(grid_width=grid[0], grid_height=grid[1], sample_fps=fps)
    times, frames = sample_frames(path, start, end - start, cfg)
    if len(times) == 0:
        return None
    return build_plan(times, frame_interest(frames, cfg), list(shots), src_w, src_h, start)


def face_plan_for_clip(source: SourceInfo, candidate: ClipCandidate, cuts: list[float]):
    """Face-tracked plan, or ``None`` to let the activity tracker answer.

    Never raises: a missing package, a missing model or an unreadable frame all
    mean "this machine cannot do faces", not "this clip has no framing".
    """
    from . import faces as facemod
    from .scenes import shots_between

    cfg = SETTINGS.framing
    if not cfg.face_model or not facemod.available(cfg.face_model):
        return None
    if source.width <= 0 or source.height <= 0:
        return None
    path = Path(source.path).resolve()
    if not path.exists():
        return None
    shots = shots_between(cuts, candidate.start, candidate.end, cfg.min_shot_s)
    detect_cfg = FramingConfig(
        grid_width=cfg.detect_width,
        grid_height=max(2, round(cfg.detect_width * 9 / 16)),
        sample_fps=cfg.detect_fps,
        face_model=cfg.face_model,
        detect_fps=cfg.detect_fps,
    )
    times, frames = sample_frames(
        path, candidate.start, candidate.end - candidate.start, detect_cfg
    )
    if len(times) == 0 or frames.size == 0:
        return None
    # The sampler hands back RGB; YuNet and cv2 expect BGR.
    bgr = np.ascontiguousarray(frames[..., ::-1])
    try:
        detections = facemod.detect(list(bgr), cfg.face_model, cfg.face_score)
    except Exception:  # noqa: BLE001 - optional dependency, never fatal
        return None
    return plan_from_detections(
        times,
        detections,
        shots,
        source.width,
        source.height,
        candidate.start,
        detect_fps=cfg.detect_fps,
        deadband=cfg.deadband_px,
        max_knots=cfg.max_knots,
    )


def plan_for_clip(
    source: SourceInfo,
    candidate: ClipCandidate,
    cuts: list[float],
) -> CropPlan | None:
    """Crop plan for one clip, or ``None`` when the media cannot be sampled."""
    from .scenes import shots_between

    cfg = SETTINGS.framing
    if source.width <= 0 or source.height <= 0:
        return None
    path = Path(source.path).resolve()
    if not path.exists():
        return None
    face_plan = face_plan_for_clip(source, candidate, cuts)
    if face_plan is not None:
        return face_plan
    shots = shots_between(cuts, candidate.start, candidate.end, cfg.min_shot_s)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return _cached_plan(
        str(path),
        mtime,
        round(candidate.start, 3),
        round(candidate.end, 3),
        source.width,
        source.height,
        tuple((round(a, 3), round(b, 3)) for a, b in shots),
        (cfg.grid_width, cfg.grid_height),
        cfg.sample_fps,
    )
