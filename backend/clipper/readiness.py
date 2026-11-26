"""One answer to "can this machine make a clip right now?".

The setup cards read this instead of stitching /api/hardware and /api/models
together. Each of those probes the machine separately - the GPU and free memory
probes shell out on Windows - so two calls a second apart can disagree about
available memory, which looks like a bug in the wizard. One probe, one verdict.

Everything here is a statement about the machine right now. Nothing is cached
across calls: "needs a model" is true until the model is actually installed.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from . import hardware, models
from .config import SETTINGS
from .llm.scorer import probe_runner

# Plain-language readings of the hardware tier. The tier letter stays in the
# payload for the Setup dialog; people never see it in the setup cards.
TIER_NOTES = {
    "A": "Runs on the CPU, so it is slower rather than limited.",
    "B": "Uses the graphics chip's shared memory. One job at a time is comfortable.",
    "C": "Comfortable: a full speech model and a small scoring model both fit.",
    "D": "Fast: the largest speech model and a 14B scoring model fit.",
    "E": "Headroom to spare, including a 32B scoring model.",
}

ENV_RUNNER = "CLIPPER_LLAMA_URL"


def _bin_dir() -> Path:
    """Where whisper-cli is looked for: <data>/bin, beside <data>/models."""
    return (models.models_dir() / ".." / "bin").resolve()


def normalize_url(raw: str) -> str:
    """Return the stored form of a scoring-runner address.

    Deliberately strict: this string is handed to an HTTP client, so it has to
    be an http(s) URL with a host and no embedded credentials. An empty string
    means "no runner", which is a valid choice rather than an error.
    """
    value = (raw or "").strip().rstrip("/")
    if not value:
        return ""
    if len(value) > 300:
        raise ValueError("That address is too long.")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Start the address with http:// or https://.")
    if not parsed.hostname:
        raise ValueError("That address is missing a host name.")
    if parsed.username or parsed.password:
        raise ValueError("Remove the username and password from the address.")
    return value


def runner_settings() -> dict:
    """The scoring runner as configured, plus whether it answers right now."""
    url = SETTINGS.llama_url or ""
    source = "env" if os.environ.get(ENV_RUNNER) else ("config" if url else "none")
    probe = (
        probe_runner(url)
        if url
        else {"reachable": False, "models": [], "error": "No address set."}
    )
    return {"url": url, "source": source, "editable": source != "env", **probe}


def save_runner(raw: str) -> dict:
    """Persist a runner address. Raises when the environment owns it."""
    if os.environ.get(ENV_RUNNER):
        raise PermissionError(ENV_RUNNER)
    SETTINGS.llama_url = normalize_url(raw)
    models.save()
    return runner_settings()


def _framing_status() -> dict:
    """Face tracking as a capability, with the same state the render will see."""
    from .pipeline import faces

    path = SETTINGS.framing.face_model or models.face_model_path()
    status = faces.status(path)
    return {
        "available": status["available"],
        "engine": "face" if status["available"] else "activity",
        "cv2": status["cv2"],
        "model_installed": status["model_installed"],
        "hint": status["hint"],
    }


def snapshot() -> dict:
    """Everything the setup cards need, from a single probe."""
    profile = hardware.probe()
    tier = hardware.classify_tier(profile)
    advice = hardware.advise(profile)
    items = models.statuses(tier)
    bin_dir = _bin_dir()
    whisper_cli = hardware.find_whisper_cli([bin_dir])
    active_asr = SETTINGS.whisper_model_path
    installed_asr = [item for item in items if item.kind == "asr" and item.installed]
    recommended = advice.get("asr") or {}
    gpu = profile.get("primary_gpu") or {}
    memory = profile.get("memory") or {}

    return {
        "machine": {
            "os": profile.get("os", ""),
            "memory_gb": round(float(memory.get("total_gb") or 0), 1),
            "gpu": gpu.get("name", ""),
            "vram_gb": round(float(gpu.get("vram_gb") or 0), 1),
            "tier": tier,
            "note": TIER_NOTES.get(tier, ""),
        },
        "video": {
            "ffmpeg": bool(profile.get("ffmpeg")),
            "disk_free_gb": profile.get("disk_free_gb", 0),
        },
        "speech": {
            # Both halves are needed: a model file and something to run it.
            "ready": bool(whisper_cli and (active_asr or installed_asr)),
            "model": Path(active_asr).name if active_asr else "",
            "whisper_cli": whisper_cli,
            "bin_dir": str(bin_dir),
            "recommended": (
                {
                    "id": recommended.get("id", ""),
                    "label": recommended.get("label", ""),
                    "size_gb": recommended.get("size_gb", 0),
                    "speed": recommended.get("speed", ""),
                }
                if recommended
                else None
            ),
        },
        "framing": _framing_status(),
        "scoring": {"built_in": True, "runner": runner_settings()},
        "models": {
            "dir": str(models.models_dir()),
            "available_gb": models.available_gb(),
        },
    }
