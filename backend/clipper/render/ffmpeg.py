"""ffmpeg argument construction for vertical clip renders.

Arguments are built as pure data (a list) so the graph can be asserted in tests
without spawning a process. The ASS file is referenced by basename and ffmpeg is
run with ``cwd`` set to its directory - that sidesteps the Windows colon and
backslash escaping rules inside filter strings, which are a reliable source of
silently dropped captions.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

FRAMINGS = ("auto", "blur", "crop")


@dataclass
class RenderSpec:
    src: Path
    out: Path
    start: float
    duration: float
    ass_name: str
    framing: str = "blur"
    width: int = 1080
    height: int = 1920
    encoder: str = ""
    crf: int = 21
    preset: str = "veryfast"
    threads: int = 0
    blur_sigma: int = 24
    loudness_lufs: float = -14.0
    # "auto" framing only: source-pixel width of the 9:16 column and the
    # time-varying x expression produced by pipeline.framing.
    crop_w: int = 0
    crop_expr: str = ""

    @property
    def duration_s(self) -> float:
        return max(0.05, self.duration)


@lru_cache(maxsize=1)
def available_encoders() -> frozenset[str]:
    try:
        output = subprocess.run(
            [FFMPEG, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return frozenset()
    return frozenset(token for token in ("h264_nvenc", "h264_amf", "libx264") if token in output)


def choose_encoder() -> str:
    """First encoder that actually works, not just one that exists.

    ffmpeg ships h264_nvenc compiled in even on machines with no NVIDIA driver,
    where it fails at open time with 'Cannot load nvcuda.dll'. Availability is
    therefore verified by encoding one frame.
    """
    working = working_encoders()
    return working[0] if working else "libx264"


@lru_cache(maxsize=1)
def working_encoders() -> tuple[str, ...]:
    available = available_encoders()
    usable: list[str] = []
    for name in ("h264_nvenc", "h264_amf"):
        if name not in available:
            continue
        probe = [
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
            "-frames:v", "1", "-c:v", name, "-f", "null", "-",
        ]
        try:
            result = subprocess.run(probe, capture_output=True, timeout=25)
        except (subprocess.SubprocessError, OSError):
            continue
        if result.returncode == 0:
            usable.append(name)
    if "libx264" in available:
        usable.append("libx264")
    return tuple(usable)


def build_filter_graph(spec: RenderSpec) -> str:
    w, h = spec.width, spec.height
    ass = f"ass={spec.ass_name}"
    if spec.framing == "auto" and spec.crop_w > 0:
        # Follow the subject: crop a 9:16 column out of the source, moving x per
        # frame, then scale to the delivery size. Quotes keep ffmpeg's filter
        # parser from reading the commas inside the if() chain as separators.
        x = spec.crop_expr or "0"
        return (
            f"[0:v]crop={spec.crop_w}:ih:x='{x}':y=0,"
            f"scale={w}:{h},{ass}[v]"
        )
    if spec.framing == "auto":
        # No plan (the media could not be sampled): a still centre crop. "auto"
        # promised a crop, so falling through to the blur pad would silently
        # deliver a different look than the one that was asked for.
        return (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},{ass}[v]"
        )
    if spec.framing == "crop":
        return (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},{ass}[v]"
        )
    # Blur a quarter-size copy and scale it back up: the result is visually the
    # same at this radius, and the gaussian runs on 1/16th of the pixels.
    sigma = max(0.5, spec.blur_sigma / 4.0)
    return (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},scale=iw/4:ih/4,gblur=sigma={sigma:g},scale={w}:{h}[bgb];"
        f"[fg]scale={w}:-2:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,{ass}[v]"
    )


def encoder_args(spec: RenderSpec) -> list[str]:
    encoder = spec.encoder or "libx264"
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(spec.crf + 2), "-pix_fmt", "yuv420p"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                "-qp_i", str(spec.crf + 1), "-qp_p", str(spec.crf + 1), "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", spec.preset, "-crf", str(spec.crf), "-pix_fmt", "yuv420p"]


def build_args(spec: RenderSpec) -> list[str]:
    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    if spec.start > 0:
        args += ["-ss", f"{spec.start:.3f}"]
    args += ["-i", str(spec.src), "-t", f"{spec.duration_s:.3f}"]
    args += ["-filter_complex", build_filter_graph(spec), "-map", "[v]", "-map", "0:a:0?"]
    args += encoder_args(spec)
    if spec.threads > 0:
        args += ["-threads", str(spec.threads)]
    args += [
        "-af", f"loudnorm=I={spec.loudness_lufs}:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        str(spec.out),
    ]
    return args


def ffprobe_duration(path: Path) -> float:
    try:
        output = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        return float(output)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0
