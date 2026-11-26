"""Face detection and subject tracking for the auto-reframer.

Optional by design. OpenCV and the YuNet model are never imported at module load:
without them every function here reports "unavailable" and the existing
motion+skin activity tracker stays the default. A missing optional dependency
must never turn into a blank reel or a crash mid-render.

The detector sees small, downscaled frames (320x180) because the only question
being asked is "where in the frame is the face", and answering that on a 4K
frame costs about forty times as much for the same answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DETECT_WIDTH = 320
DETECT_HEIGHT = 180
DEFAULT_SCORE = 0.6


@dataclass
class Face:
    x: float
    y: float
    w: float
    h: float
    score: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)


@dataclass
class Track:
    id: int
    boxes: list[Face]
    times: list[float]
    # Filled in from frame pixels when they are available; 0.0 otherwise, rather
    # than inventing motion for boxes that were never measured.
    mouth: float = 0.0

    @property
    def median(self) -> Face:
        boxes = sorted(self.boxes, key=lambda box: box.area)
        return boxes[len(boxes) // 2] if boxes else Face(0, 0, 0, 0)

    @property
    def mouth_activity(self) -> float:
        """How much the lower half of the box changes between frames.

        Not lip-reading: it is the cheapest signal that separates the person
        talking from the person listening, and it is documented as such.
        """
        return self.mouth


def available(model_path: str | Path | None = None) -> bool:
    """True only when both the detector library and the model are present."""
    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means unavailable
        return False
    if not model_path:
        return False
    return Path(model_path).exists()


def status(model_path: str | Path | None = None) -> dict:
    has_cv2 = False
    try:
        import cv2  # noqa: F401

        has_cv2 = True
    except Exception:  # noqa: BLE001
        has_cv2 = False
    model = Path(model_path) if model_path else None
    has_model = bool(model and model.exists())
    if has_cv2 and has_model:
        hint = ""
    elif has_cv2:
        hint = "The face model is not installed, so framing follows motion instead."
    else:
        hint = (
            "Face-aware framing needs the optional OpenCV package. "
            "Framing follows motion instead."
        )
    return {
        "available": has_cv2 and has_model,
        "engine": "opencv-yunet" if has_cv2 else "activity",
        "model": str(model or ""),
        "hint": hint,
    }


def detect(
    frames: list,
    model_path: str | Path | None = None,
    score: float = DEFAULT_SCORE,
) -> list[list[Face]]:
    """Faces per frame. Frames are already-resized BGR arrays, or paths to them.

    Isolated so tests can monkeypatch it and so a detector failure in one frame
    does not abort an analysis.
    """
    if not available(model_path):
        return [[] for _ in frames]
    import cv2

    detector = cv2.FaceDetectorYN.create(
        str(model_path), "", (DETECT_WIDTH, DETECT_HEIGHT), score, 0.3, 5000
    )
    out: list[list[Face]] = []
    for frame in frames:
        image = frame
        if isinstance(frame, (str, Path)):
            image = cv2.imread(str(frame))
            if image is None:
                out.append([])
                continue
        try:
            height, width = image.shape[:2]
            scale_x = width / DETECT_WIDTH
            scale_y = height / DETECT_HEIGHT
            resized = cv2.resize(image, (DETECT_WIDTH, DETECT_HEIGHT))
            _, faces = detector.detect(resized)
        except Exception:  # noqa: BLE001 - a bad frame is not a failed render
            out.append([])
            continue
        found: list[Face] = []
        for row in faces if faces is not None else []:
            x, y, w, h = (float(value) for value in row[:4])
            out_score = float(row[-1]) if len(row) > 14 else 0.0
            found.append(Face(x * scale_x, y * scale_y, w * scale_x, h * scale_y, out_score))
        out.append(found)
    return out


def _iou(a: Face, b: Face) -> float:
    left = max(a.x, b.x)
    top = max(a.y, b.y)
    right = min(a.x + a.w, b.x + b.w)
    bottom = min(a.y + a.h, b.y + b.h)
    overlap = max(0.0, right - left) * max(0.0, bottom - top)
    union = a.area + b.area - overlap
    return overlap / union if union > 0 else 0.0


def track(faces_per_frame: list[list[Face]], times: list[float], fps: float = 4.0) -> list[Track]:
    """Associate boxes across frames by overlap, then nearest centre.

    A track that disappears for more than a second is closed; the subject can
    walk out of frame and back without being mistaken for the same person.
    """
    tracks: list[Track] = []
    last_seen: dict[int, int] = {}
    active: list[Track] = []
    gap_limit = max(1, int(round(fps)))
    for index, boxes in enumerate(faces_per_frame):
        when = times[index] if index < len(times) else index / max(0.1, fps)
        active = [track for track in active if index - last_seen[track.id] <= gap_limit]
        matched: set[int] = set()
        next_active: list[Track] = []
        for face in boxes:
            best: Track | None = None
            best_score = 0.0
            for candidate in active:
                if candidate.id in matched:
                    continue
                previous = candidate.boxes[-1]
                overlap = _iou(previous, face)
                distance = abs(previous.cx - face.cx) + abs(previous.y - face.y)
                score = overlap if overlap > 0 else max(0.0, 1.0 - distance / 480.0)
                if score > best_score:
                    best_score, best = score, candidate
            if best is not None and best_score >= 0.15:
                best.boxes.append(face)
                best.times.append(when)
                matched.add(best.id)
                last_seen[best.id] = index
                next_active.append(best)
            else:
                created = Track(id=len(tracks) + 1, boxes=[face], times=[when])
                tracks.append(created)
                last_seen[created.id] = index
                next_active.append(created)
        active = next_active
    return tracks


def choose_subject(
    tracks: list[Track],
    shot_start: float,
    shot_end: float,
    crop_w: float,
    frame_width: float,
) -> tuple[Track | None, str]:
    """The person worth following in one shot, and the reason why."""
    if not tracks:
        return None, "no faces detected"
    inside = [
        track
        for track in tracks
        if track.times and shot_start <= track.times[0] <= shot_end
    ] or tracks
    if len(inside) >= 2:
        first, second = sorted(inside, key=lambda t: t.median.cx)[:2]
        if abs(first.median.cx - second.median.cx) <= crop_w:
            return first, "two subjects fit the crop; following the first"
    ranked = sorted(
        inside,
        key=lambda track: (track.mouth_activity, track.median.area),
        reverse=True,
    )
    best = ranked[0]
    if best.mouth_activity > 0:
        return best, "largest speaking face"
    if len(inside) > 1:
        centre = frame_width / 2.0
        closest = min(inside, key=lambda track: abs(track.median.cx - centre))
        if closest is best:
            return best, "largest face near the centre"
        return closest, "largest face was off-centre; following the centred one"
    return best, "only face in shot"


def plan_curve(track: Track, crop_w: float, frame_width: float) -> list[tuple[float, float]]:
    """Clip-relative (time, crop-left) knots that keep the subject centred."""
    knots: list[tuple[float, float]] = []
    for when, box in zip(track.times, track.boxes):
        left = box.cx - crop_w / 2.0
        left = max(0.0, min(frame_width - crop_w, left))
        knots.append((round(when, 3), round(left, 1)))
    return knots
