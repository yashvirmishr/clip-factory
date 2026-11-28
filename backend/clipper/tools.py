"""Install the external programs the pipeline shells out to.

Every cut runs ffmpeg, every real transcript runs whisper.cpp. Neither ships
in the repository, and "unpack this zip into a hidden data folder" is where a
fresh install stops working. This module pins one known-good build of each,
verifies its SHA-256, and unpacks only the executables into ``<data>/bin``,
which is already first on PATH.

Automatic install is Windows-only because that is the only platform this app
packages. Elsewhere the manual route still works, and ``status()`` says so
instead of offering a button that cannot finish.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import platform
import shutil
import struct
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import ensure_tools_on_path, tools_dir

USER_AGENT = "ClipFactory/0.1"


@dataclass(frozen=True)
class Tool:
    id: str
    label: str
    version: str
    url: str
    sha256: str
    size: int
    license: str
    homepage: str
    provides: tuple[str, ...]
    patterns: tuple[str, ...]


# Pinned builds, not "latest": a URL that moves breaks the checksum and turns
# install into a silent corruption. Bump the version and the hash together.
TOOLS: dict[str, Tool] = {
    "ffmpeg": Tool(
        id="ffmpeg",
        label="ffmpeg",
        version="9.1",
        url="https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.1-essentials_build.zip",
        sha256="b9bbbb3acece000cbeec994f856649354e52c773807841e78908374b24d658fd",
        size=119_467_219,
        license="GPLv3",
        homepage="https://ffmpeg.org/",
        provides=("ffmpeg.exe", "ffprobe.exe"),
        patterns=("ffmpeg.exe", "ffprobe.exe"),
    ),
    "whisper": Tool(
        id="whisper",
        label="whisper.cpp",
        version="1.7.6",
        url="https://github.com/ggml-org/whisper.cpp/releases/download/v1.7.6/whisper-bin-x64.zip",
        sha256="0d2eca299c248f965bd0341bcb219db4b433c7f0c0ce2200d4df85765e8156a9",
        size=3_675_974,
        license="MIT",
        homepage="https://github.com/ggml-org/whisper.cpp",
        provides=("whisper-cli.exe",),
        patterns=("whisper-cli.exe", "*.dll"),
    ),
}


def find(tool_id: str) -> Tool | None:
    return TOOLS.get(tool_id)


def automatic_install_supported() -> bool:
    """Windows x64 only: the released binaries are Windows x64 builds."""
    return os.name == "nt" and struct.calcsize("P") == 8


def _resolve(tool: Tool) -> str:
    """The path the pipeline will actually use, or an empty string."""
    from .config import SETTINGS

    configured = (SETTINGS.whisper_cli or "").strip() if tool.id == "whisper" else ""
    if configured and Path(configured).exists():
        return configured
    directory = tools_dir()
    for name in tool.provides:
        if (directory / name).exists():
            return str(directory / name)
    if tool.id == "whisper":
        from . import hardware

        return hardware.find_whisper_cli([directory])
    return shutil.which(tool.provides[0]) or ""


def _installed(tool: Tool) -> bool:
    if tool.id == "whisper":
        return bool(_resolve(tool))
    return all(
        (tools_dir() / name).exists() or shutil.which(name) for name in tool.provides
    )


def status() -> dict:
    """One answer to "are the two programs present, and can I install them?"""
    directory = tools_dir()
    automatic = automatic_install_supported()
    return {
        "bin_dir": str(directory),
        "automatic": automatic,
        "platform": f"{platform.system()} {platform.machine()}".strip(),
        "tools": [
            {
                "id": tool.id,
                "label": tool.label,
                "version": tool.version,
                "size_mb": round(tool.size / 1_000_000, 1),
                "license": tool.license,
                "homepage": tool.homepage,
                "installed": _installed(tool),
                "path": _resolve(tool),
            }
            for tool in TOOLS.values()
        ],
    }


def _check_platform() -> None:
    if not automatic_install_supported():
        raise RuntimeError(
            "Automatic install is available on Windows x64 only. Install "
            "ffmpeg and whisper-cli yourself, then press Check again."
        )


def _check_space(tool: Tool) -> None:
    directory = tools_dir()
    directory.mkdir(parents=True, exist_ok=True)
    needed = int(tool.size * 2.5) + 50_000_000
    free = shutil.disk_usage(directory).free
    if free < needed:
        raise RuntimeError(
            f"Not enough free space in {directory}: need about "
            f"{needed / 1e9:.1f} GB, have {free / 1e9:.1f} GB."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(tool: Tool, dest: Path, progress) -> None:
    """Resumable download with a progress callback, in the job-lane shape."""
    existing = dest.stat().st_size if dest.exists() else 0
    request = urllib.request.Request(tool.url, headers={"User-Agent": USER_AGENT})
    if existing:
        request.add_header("Range", f"bytes={existing}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        resumed = existing > 0 and getattr(response, "status", 200) == 206
        written = existing if resumed else 0
        total = int(response.headers.get("Content-Length") or 0) + written
        total = max(total, tool.size)
        mode = "ab" if resumed else "wb"
        with dest.open(mode) as handle:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                progress(min(0.99, written / total), written, total)


def _member_name(info: zipfile.ZipInfo) -> str:
    name = info.filename.replace("\\", "/")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if name.startswith("/") or ".." in parts:
        raise RuntimeError(f"{info.filename!r} in the archive is not a safe path.")
    return parts[-1] if parts else ""


def _extract(archive: Path, tool: Tool, destination: Path) -> list[str]:
    """Copy only the matching files, flat, rejecting paths that escape."""
    written: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            name = _member_name(info)
            if not name:
                continue
            lowered = name.lower()
            if not any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in tool.patterns):
                continue
            target = destination / name
            with bundle.open(info) as source, tempfile.NamedTemporaryFile(
                dir=destination, prefix=name + ".", suffix=".part", delete=False
            ) as handle:
                temporary = Path(handle.name)
                try:
                    shutil.copyfileobj(source, handle, 1 << 20)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                os.replace(temporary, target)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Could not replace {target.name}. Close any running ffmpeg "
                    "or whisper job and try again."
                ) from exc
            written.append(name)
    return written


def install(tool_id: str, progress=None) -> dict:
    """Download, verify and unpack one tool. Returns the fresh status."""
    tool = TOOLS.get(tool_id)
    if tool is None:
        raise KeyError(tool_id)
    _check_platform()
    _check_space(tool)
    directory = tools_dir()
    report = progress or (lambda *_: None)
    part = directory / f".{tool.id}.download"
    report("download", 0.0, f"{tool.label} {tool.version}")

    def download_progress(fraction: float, written: int, total: int) -> None:
        report(
            "download",
            round(fraction * 0.85, 4),
            f"{tool.label} {written / 1e6:.0f} of {total / 1e6:.0f} MB",
        )

    # A previous attempt may have finished writing but not reached the hash
    # check. Skip the request, keep the file, and let verify decide.
    if not (part.exists() and part.stat().st_size == tool.size):
        _download(tool, part, download_progress)
    report("verify", 0.86, "checking the download")
    digest = _sha256(part)
    if digest != tool.sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(
            f"The {tool.label} download did not match its pinned SHA-256, so it "
            "was deleted. Check the connection or try again."
        )
    report("unpack", 0.9, f"unpacking {tool.label}")
    written = _extract(part, tool, directory)
    part.unlink(missing_ok=True)
    missing = [name for name in tool.provides if not (directory / name).exists()]
    if missing:
        absent = ", ".join(missing)
        raise RuntimeError(f"The {tool.label} archive did not contain {absent}.")
    ensure_tools_on_path()
    report("done", 1.0, f"{tool.label} installed")
    return {
        "tool": tool.id,
        "version": tool.version,
        "files": written,
        "status": status(),
    }

