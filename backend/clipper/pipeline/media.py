"""Media probing, audio extraction and per-frame feature extraction.

Memory discipline: audio is streamed from disk in 60 s blocks. A 4 h VOD is
~460 MB of 16 kHz PCM and is never held in RAM as one array; only the derived
per-frame series (a few MB) and the peak pyramid survive.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import AudioConfig

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

BLOCK_SECONDS = 60.0
PEAK_LEVELS = (64, 256, 1024, 4096)


class MediaError(RuntimeError):
    pass


@dataclass
class AudioAnalysis:
    frame_rate: float
    rms: np.ndarray
    flux: np.ndarray
    zcr: np.ndarray
    mask: np.ndarray  # bool per frame: speech-ish
    duration: float

    def bucket(self, start: float, end: float, series: np.ndarray, reducer: str = "mean") -> float:
        lo = max(0, int(start * self.frame_rate))
        hi = min(len(series), int(end * self.frame_rate))
        if hi <= lo:
            return 0.0
        chunk = series[lo:hi]
        return float(chunk.mean() if reducer == "mean" else chunk.max())

    def coverage(self, start: float, end: float) -> float:
        lo = max(0, int(start * self.frame_rate))
        hi = min(len(self.mask), int(end * self.frame_rate))
        if hi <= lo:
            return 0.0
        return float(self.mask[lo:hi].mean())


def run(cmd: list[str], timeout: float = 3600.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise MediaError(f"{cmd[0]} not found on PATH. Install ffmpeg and retry.") from exc


def probe(path: str | Path) -> dict:
    """ffprobe -> a small, stable dict (never the raw 100 KB JSON)."""
    result = run(
        [
            FFPROBE, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed for {path}: {result.stderr.strip()[:400]}")
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0 and video:
        try:
            duration = float(video.get("duration", 0.0))
        except (TypeError, ValueError):
            duration = 0.0
    fps = 0.0
    if video and video.get("avg_frame_rate", "0/0") not in ("0/0", "", None):
        num, _, den = str(video["avg_frame_rate"]).partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            fps = 0.0
    return {
        "duration": duration,
        "width": int(video.get("width", 0)) if video else 0,
        "height": int(video.get("height", 0)) if video else 0,
        "fps": round(fps, 3),
        "has_audio": audio is not None,
        "size_bytes": int(data.get("format", {}).get("size", 0) or 0),
        "format": data.get("format", {}).get("format_name", ""),
    }


def extract_audio(src: str | Path, out_wav: str | Path, cfg: AudioConfig) -> Path:
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if out_wav.exists() and out_wav.stat().st_size > 44:
        return out_wav
    result = run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src),
            "-vn", "-ac", "1", "-ar", str(cfg.sample_rate),
            "-c:a", "pcm_s16le", str(out_wav),
        ]
    )
    if result.returncode != 0:
        raise MediaError(f"ffmpeg audio extraction failed: {result.stderr.strip()[:400]}")
    return out_wav


def _speech_mask(rms: np.ndarray, flux: np.ndarray, frame_rate: float) -> np.ndarray:
    """Cheap VAD: energy above an adaptive floor, smoothed over ~300 ms.

    Not a replacement for Silero VAD in whisper.cpp - it exists so the pipeline
    can report speech coverage for the quality gates even when ASR runs in
    "import my SRT" mode with no audio model available.
    """
    if rms.size == 0:
        return np.zeros(0, dtype=bool)
    win = max(1, int(5.0 * frame_rate))
    kernel = np.ones(win, dtype=np.float32) / win
    rolling = np.convolve(rms, kernel, mode="same")
    peak = float(np.percentile(rms, 95)) or 1e-6
    threshold = np.maximum(0.12 * rolling, 0.02 * peak)
    mask = (rms > threshold) & (rms > 1e-4)
    smooth = max(1, int(0.3 * frame_rate))
    if smooth > 1 and mask.size > smooth:
        padded = np.convolve(mask.astype(np.float32), np.ones(smooth) / smooth, mode="same")
        mask = padded > 0.5
    return mask


def compute_features(wav_path: str | Path, cfg: AudioConfig) -> AudioAnalysis:
    wav_path = Path(wav_path)
    with wave.open(str(wav_path), "rb") as handle:
        sr = handle.getframerate()
        total = handle.getnframes()
        frame_len = max(1, int(sr * cfg.frame_ms / 1000))
        hop = frame_len
        n_frames = max(1, (total - frame_len) // hop + 1)
        rms = np.zeros(n_frames, dtype=np.float32)
        flux = np.zeros(n_frames, dtype=np.float32)
        zcr = np.zeros(n_frames, dtype=np.float32)
        window = np.hanning(cfg.fft_size).astype(np.float32)
        prev_mag = None

        block_frames = max(1, int(BLOCK_SECONDS * sr / hop))
        idx = 0
        handle.setpos(0)
        while idx < n_frames:
            count = min(block_frames, n_frames - idx)
            raw = handle.readframes(count * hop)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            usable = (len(samples) // hop) * hop
            samples = samples[:usable]
            frames = samples.reshape(-1, hop)
            n = frames.shape[0]
            for i in range(n):
                frame = frames[i]
                rms[idx + i] = float(np.sqrt(np.mean(frame * frame) + 1e-12))
                signs = np.signbit(frame)
                zcr[idx + i] = float(np.mean(signs[1:] != signs[:-1])) if frame.size > 1 else 0.0
                seg = frame[: cfg.fft_size]
                if seg.size < cfg.fft_size:
                    seg = np.pad(seg, (0, cfg.fft_size - seg.size))
                mag = np.abs(np.fft.rfft(seg * window))
                if prev_mag is not None:
                    flux[idx + i] = float(np.sum(np.maximum(0.0, mag - prev_mag)))
                prev_mag = mag
            idx += n

    # Normalise flux to a comparable 0..1 range.
    if flux.max() > 0:
        flux = flux / float(np.percentile(flux, 99) or flux.max())
        flux = np.clip(flux, 0.0, 1.0)

    frame_rate = sr / hop
    mask = _speech_mask(rms, flux, frame_rate)
    duration = total / float(sr) if sr else 0.0
    return AudioAnalysis(
        frame_rate=frame_rate, rms=rms, flux=flux, zcr=zcr, mask=mask, duration=duration
    )


def peak_pyramid(wav_path: str | Path, levels: tuple[int, ...] = PEAK_LEVELS) -> dict[str, np.ndarray]:
    """Min/max pairs per bucket at several zoom levels - the UI waveform."""
    with wave.open(str(wav_path), "rb") as handle:
        total = handle.getnframes()
        handle.setpos(0)
        samples = np.frombuffer(handle.readframes(total), dtype=np.int16).astype(np.float32)
    samples /= 32768.0
    out: dict[str, np.ndarray] = {"count": np.array([samples.size], dtype=np.int64)}
    for level in levels:
        buckets = samples.size // level
        if buckets == 0:
            out[f"min{level}"] = np.zeros(0, dtype=np.float32)
            out[f"max{level}"] = np.zeros(0, dtype=np.float32)
            continue
        trimmed = samples[: buckets * level].reshape(buckets, level)
        out[f"min{level}"] = trimmed.min(axis=1)
        out[f"max{level}"] = trimmed.max(axis=1)
    return out


def load_peaks(path: str | Path, level: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    data = np.load(str(path))
    return data[f"min{level}"], data[f"max{level}"]
