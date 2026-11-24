"""Fetch a VOD from a URL: Twitch, YouTube, or anything else yt-dlp knows.

Two things this deliberately does *not* do:

* it does not download a playlist. A channel URL with 400 VODs behind it should
  never silently start a 300 GB job;
* it does not let yt-dlp pick a codec. The format is pinned to H.264 + AAC in
  MP4, because the handoff target has its own decoders and no ffmpeg - an AV1 or
  VP9 file downloads fine and then fails to import, which is a much worse failure
  than a slightly larger download.

yt-dlp is a Python package rather than a required dependency: the app imports it
lazily, and says exactly what to install when it is missing instead of failing
with an ImportError four layers deep.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# H.264/AAC first (universal), then anything, because a download that works beats
# a download that is perfectly compatible and never finishes.
FORMAT = "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b"
MIN_BYTES = 10_000


class FetchError(RuntimeError):
    pass


@dataclass
class Fetched:
    path: Path
    title: str
    duration: float
    video_id: str
    url: str
    skipped: bool = False


def is_url(value: str | Path) -> bool:
    text = str(value).strip().lower()
    return text.startswith(("http://", "https://")) and len(text) > 8


def available() -> str:
    """yt-dlp version, or empty string when it is not installed."""
    try:
        import yt_dlp  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not usable"
        return ""
    try:
        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return "unknown"


def _require() -> None:
    if not available():
        raise FetchError(
            "URL import needs yt-dlp: run "
            "`./.venv/Scripts/python.exe -m pip install yt-dlp` "
            "(a `yt-dlp` binary on PATH is not enough - the app uses the module)."
        )


def fetch(
    url: str,
    out_dir: Path,
    progress=None,
    max_height: int = 1080,
    timeout: int = 6 * 3600,
) -> Fetched:
    """Download one video into ``out_dir`` and return what landed on disk."""
    _require()
    import yt_dlp

    url = url.strip()
    out_dir.mkdir(parents=True, exist_ok=True)

    def hook(status: dict) -> None:
        if not progress:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            fraction = (done / total) if total else 0.0
            speed = status.get("speed") or 0
            detail = f"{done / 1e6:.0f} MB"
            if total:
                detail += f" / {total / 1e6:.0f} MB"
            if speed:
                detail += f" · {speed / 1e6:.1f} MB/s"
            progress(min(0.99, fraction), detail)
        elif status.get("status") == "finished":
            progress(0.99, "merging")

    options = {
        "format": FORMAT,
        "format_sort": [f"res:{max_height}", "ext:mp4:m4a", "codec:h264"],
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "playlist_items": "1",
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "continuedl": True,
        "progress_hooks": [hook],
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:  # type: ignore[attr-defined]
        raise FetchError(_clean(str(exc))) from exc
    except Exception as exc:  # noqa: BLE001
        raise FetchError(_clean(f"{type(exc).__name__}: {exc}")) from exc

    if not info:
        raise FetchError("yt-dlp returned no metadata for that URL")
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise FetchError("that URL is a playlist with nothing playable in it")
        info = entries[0]

    path = _locate(info, out_dir)
    if path is None or not path.exists() or path.stat().st_size < MIN_BYTES:
        raise FetchError("download finished but no usable file appeared on disk")

    return Fetched(
        path=path,
        title=str(info.get("title") or path.stem),
        duration=float(info.get("duration") or 0.0),
        video_id=str(info.get("id") or path.stem),
        url=url,
    )


def _locate(info: dict, out_dir: Path) -> Path | None:
    requested = info.get("requested_downloads") or []
    for item in requested:
        candidate = item.get("filepath")
        if candidate and Path(candidate).exists():
            return Path(candidate)
    stem = str(info.get("id") or "")
    for candidate in out_dir.glob(f"{stem}.*"):
        if candidate.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            return candidate
    return None


def _clean(message: str, limit: int = 300) -> str:
    """yt-dlp errors are multi-line and start with 'ERROR:'; keep the useful part."""
    text = " ".join(message.replace("ERROR:", "").split())
    return text[:limit] or "download failed"
