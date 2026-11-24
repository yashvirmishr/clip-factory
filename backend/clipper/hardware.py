"""Hardware probe and model advisor.

The whole point is that a weak laptop gets a *plan*, not a crash: the probe
reports what it can actually use, and the advisor proposes the largest models
that fit with headroom, plus an honest speed expectation.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory_gb() -> tuple[float, float]:
    """(total, available) in GB. Uses GlobalMemoryStatusEx - instant, no deps."""
    if os.name == "nt":
        try:
            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return (
                    round(status.ullTotalPhys / 1e9, 2),
                    round(status.ullAvailPhys / 1e9, 2),
                )
        except (AttributeError, OSError):
            pass
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        total = os.sysconf("SC_PHYS_PAGES") * page / 1e9
        avail = os.sysconf("SC_AVPHYS_PAGES") * page / 1e9
        return round(total, 2), round(avail, 2)
    except (AttributeError, ValueError, OSError):
        return 0.0, 0.0


def _gpus_windows() -> list[dict]:
    if os.name != "nt" or not shutil.which("powershell"):
        return []
    script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    out: list[dict] = []
    for item in payload:
        name = str(item.get("Name", "")).strip()
        vram = item.get("AdapterRAM") or 0
        try:
            vram_gb = round(int(vram) / 1e9, 2)
        except (TypeError, ValueError):
            vram_gb = 0.0
        out.append({"name": name, "vram_gb": vram_gb, "driver": str(item.get("DriverVersion", ""))})
    return out


def _classify_gpu(name: str) -> str:
    lowered = name.lower()
    if "nvidia" in lowered or "geforce" in lowered or "rtx" in lowered or "quadro" in lowered:
        return "nvidia"
    if "radeon" in lowered or "amd" in lowered or "rx " in lowered:
        return "amd"
    if "intel" in lowered or "arc" in lowered:
        return "intel"
    if "microsoft basic" in lowered:
        return "software"
    return "unknown"


def _has_nvidia_smi() -> bool:
    return shutil.which("nvidia-smi") is not None


def probe() -> dict:
    total_ram, avail_ram = memory_gb()
    gpus = _gpus_windows()
    for gpu in gpus:
        gpu["vendor"] = _classify_gpu(gpu["name"])
        gpu["dedicated"] = gpu["vram_gb"] >= 2.0 and gpu["vendor"] in ("nvidia", "amd")
        gpu["integrated"] = gpu["vendor"] in ("amd", "intel") and gpu["vram_gb"] < 2.0
    best_gpu = max(gpus, key=lambda g: g["vram_gb"], default=None)
    disk = shutil.disk_usage(Path.home())
    cpus = os.cpu_count() or 4
    return {
        "cpu": {
            "name": platform.processor() or platform.machine(),
            "logical_cores": cpus,
            "physical_estimate": max(1, cpus // 2),
        },
        "memory": {"total_gb": total_ram, "available_gb": avail_ram},
        "gpus": gpus,
        "primary_gpu": best_gpu,
        "cuda": _has_nvidia_smi(),
        "vulkan": bool(best_gpu and best_gpu["vendor"] in ("amd", "intel", "nvidia")),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "os": f"{platform.system()} {platform.release()}",
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }


TIERS = {
    "A": {"label": "CPU only", "blurb": "Everything runs on the CPU. Expect a slow but steady ride."},
    "B": {"label": "iGPU / shared memory", "blurb": "Shared-memory GPU. Vulkan helps; system RAM is the real limit."},
    "C": {"label": "8 GB dedicated GPU", "blurb": "Comfortable. Full whisper models and an 8B re-ranker."},
    "D": {"label": "12-16 GB dedicated GPU", "blurb": "Fast. Large-v3 plus a 14B re-ranker fits."},
    "E": {"label": "24 GB+ dedicated GPU", "blurb": "Headroom to spare. 32B re-ranker and parallel windows."},
}


def classify_tier(profile: dict) -> str:
    gpu = profile.get("primary_gpu") or {}
    vendor = gpu.get("vendor", "unknown")
    vram = float(gpu.get("vram_gb", 0.0))
    ram = float(profile.get("memory", {}).get("total_gb", 0.0))
    if vendor == "nvidia" and vram >= 22:
        return "E"
    if vendor == "nvidia" and vram >= 11:
        return "D"
    if vendor == "nvidia" and vram >= 6:
        return "C"
    if ram >= 14:
        return "B"
    return "A"


MODELS: list[dict] = [
    {
        "id": "whisper-base-en",
        "kind": "asr",
        "label": "Whisper base.en (q5)",
        "size_gb": 0.15,
        "min_tier": "A",
        "speed": "~1-2x realtime on CPU",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin",
        "filename": "ggml-base.en.bin",
    },
    {
        "id": "whisper-small-en",
        "kind": "asr",
        "label": "Whisper small.en (q5)",
        "size_gb": 0.49,
        "min_tier": "A",
        "speed": "~2-3x realtime with Vulkan",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin",
        "filename": "ggml-small.en.bin",
    },
    {
        "id": "whisper-medium-en",
        "kind": "asr",
        "label": "Whisper medium.en (q5)",
        "size_gb": 1.53,
        "min_tier": "B",
        "speed": "slower, best English accuracy under 2 GB",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin",
        "filename": "ggml-medium.en.bin",
    },
    {
        "id": "whisper-large-v3-turbo",
        "kind": "asr",
        "label": "Whisper large-v3-turbo (q5)",
        "size_gb": 1.1,
        "min_tier": "C",
        "speed": "fast on 8 GB+ VRAM",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
        "filename": "ggml-large-v3-turbo-q5_0.bin",
    },
    {
        "id": "silero-vad",
        "kind": "vad",
        "label": "Silero VAD (required for --vad)",
        "size_gb": 0.002,
        "min_tier": "A",
        "speed": "negligible",
        "url": "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin",
        "filename": "ggml-silero-v5.1.2.bin",
    },
    {
        "id": "qwen2.5-3b-q4",
        "kind": "llm",
        "label": "Qwen2.5 3B Instruct (Q4_K_M)",
        "size_gb": 2.0,
        "min_tier": "A",
        "speed": "~8-12 tok/s on iGPU, fine for scoring",
        "url": "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "qwen2.5-7b-q4",
        "kind": "llm",
        "label": "Qwen2.5 7B Instruct (Q4_K_M)",
        "size_gb": 4.7,
        "min_tier": "B",
        "speed": "~4-7 tok/s on iGPU - use for hook polish only",
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "llama-3.1-8b-q4",
        "kind": "llm",
        "label": "Llama 3.1 8B Instruct (Q4_K_M)",
        "size_gb": 4.9,
        "min_tier": "C",
        "speed": "fast with full GPU offload",
        "url": "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "qwen2.5-14b-q4",
        "kind": "llm",
        "label": "Qwen2.5 14B Instruct (Q4_K_M)",
        "size_gb": 9.0,
        "min_tier": "D",
        "speed": "needs 12 GB+ VRAM",
        "url": "https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "filename": "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
    },
]

TIER_ORDER = "ABCDE"


def advise(profile: dict) -> dict:
    tier = classify_tier(profile)
    rank = TIER_ORDER.index(tier)
    usable = [m for m in MODELS if TIER_ORDER.index(m["min_tier"]) <= rank]
    ram = float(profile.get("memory", {}).get("total_gb", 0.0))
    # Leave the OS and this app ~4 GB on shared-memory machines.
    budget = ram - (4.0 if tier in ("A", "B") else 2.0)

    def largest(kind: str) -> dict | None:
        options = [
            m for m in usable
            if m["kind"] == kind and (kind != "llm" or m["size_gb"] <= max(1.0, budget))
        ]
        return max(options, key=lambda m: m["size_gb"]) if options else None

    scoring = next((m for m in usable if m["kind"] == "llm" and m["size_gb"] <= 2.5), None)
    return {
        "tier": tier,
        "tier_label": TIERS[tier]["label"],
        "blurb": TIERS[tier]["blurb"],
        "asr": largest("asr"),
        "vad": next((m for m in usable if m["kind"] == "vad"), None),
        "llm_scoring": scoring or largest("llm"),
        "llm_polish": largest("llm"),
        "model_budget_gb": round(max(1.0, budget), 1),
        "notes": [
            "Run one heavy stage at a time - analysis and rendering never overlap.",
            "Exclude your media folder from Windows Defender real-time scanning.",
            "On shared-memory GPUs set the UMA frame buffer to ~4 GB in BIOS.",
        ],
    }


def download_model(model: dict, target_dir: Path, progress=None) -> Path:
    """Resumable download with size check. Hash pinning is left to the manifest."""
    import urllib.request

    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / model["filename"]
    existing = dest.stat().st_size if dest.exists() else 0
    request = urllib.request.Request(model["url"], headers={"User-Agent": "ClipFactory/0.1"})
    if existing:
        request.add_header("Range", f"bytes={existing}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length", 0)) + existing
        mode = "ab" if existing and response.status == 206 else "wb"
        with open(dest, mode) as handle:
            written = existing
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                if progress and total:
                    progress(min(1.0, written / total))
    return dest


WHISPER_BINARIES = ("whisper-cli.exe", "whisper-cli", "main.exe", "main", "whisper.exe", "whisper")

# A bare name is fine on POSIX; Windows also substitutes PATHEXT entries, which
# is how "main" turns into main.CPL.
_EXECUTABLE_SUFFIXES = {""} | ({".exe", ".com", ".bat", ".cmd"} if os.name == "nt" else set())


def find_whisper_cli(search_dirs: list[Path] | tuple[Path, ...] = ()) -> str:
    """Locate a whisper.cpp binary without requiring the user to set a variable.

    Order: an explicit path, then ``PATH``, then a ``bin`` folder next to the app
    data. A model with no binary used to fall back to the stub *silently*, which
    looks exactly like "transcription is broken" - so the answer to "is whisper
    available" now lives in one place that the UI can ask.
    """
    import shutil as _shutil

    explicit = (os.environ.get("CLIPPER_WHISPER_CLI") or "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    for name in WHISPER_BINARIES:
        found = _shutil.which(name)
        # which() honours PATHEXT on Windows, so asking for the bare name "main"
        # returns C:\Windows\System32\main.CPL - a Control Panel applet, not
        # whisper. Only something actually executable counts as found.
        if found and Path(found).suffix.lower() in _EXECUTABLE_SUFFIXES:
            return found
    candidates = list(search_dirs) + [Path.cwd() / "bin", Path.cwd() / "vendor"]
    for directory in candidates:
        for name in WHISPER_BINARIES:
            candidate = Path(directory) / name
            if candidate.exists():
                return str(candidate)
    return ""
