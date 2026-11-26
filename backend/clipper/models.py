"""Model manager: what is installed, what fits this machine, what is in use.

The manifest and the resumable downloader existed but nothing drove them, which
left the app dependent on someone setting ``CLIPPER_WHISPER_CLI`` by hand. This is
the missing middle: list, download with progress, activate, and persist the choice
so the next launch remembers it.

Two rules that keep it from being a download button with no judgement:

* a model that does not fit in free memory is still listed and still installable,
  but it is flagged - refusing outright is wrong, silently letting someone load a
  4.7 GB model into 2 GB of headroom is worse;
* activation writes to ``config.json`` immediately, so "it works until you restart"
  is not a failure mode.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import hardware
from .config import SETTINGS

ACTIVE_KEYS = {
    "asr": "whisper_model_path",
    "vad": "vad_model_path",
    "llm": "llm_model_path",
}


@dataclass
class ModelStatus:
    id: str
    kind: str
    label: str
    size_gb: float
    min_tier: str
    speed: str
    filename: str
    installed: bool
    active: bool
    fits: bool
    path: str
    tier_ok: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "size_gb": self.size_gb,
            "min_tier": self.min_tier,
            "speed": self.speed,
            "filename": self.filename,
            "installed": self.installed,
            "active": self.active,
            "fits": self.fits,
            "path": self.path,
            "tier_ok": self.tier_ok,
        }


def models_dir() -> Path:
    path = (SETTINGS.data_dir / "models").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tier_rank(tier: str) -> int:
    return {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}.get(tier, 0)


def available_gb() -> float:
    """Free memory right now, after this app's own reserve."""
    return round(_available_gb(), 2)


def _available_gb() -> float:
    """Memory free right now. Falls back to half of total if the probe fails."""
    total, available = hardware.memory_gb()
    if available and available > 0.1:
        return available
    return total * 0.5 if total else 0.0


def _fits(size_gb: float) -> bool:
    """Does this model leave the machine usable?

    Not "fits in free minus a fixed reserve": on a busy box free memory is often
    already below the reserve, and a flat rule then claims a 150 MB model does not
    fit. A model may take at most 75% of what is free right now.
    """
    return size_gb <= _available_gb() * 0.75


def statuses(tier: str | None = None) -> list[ModelStatus]:
    if tier is None:
        tier = hardware.classify_tier(hardware.probe())
    active_paths = {getattr(SETTINGS, key, "") for key in ACTIVE_KEYS.values()}
    out: list[ModelStatus] = []
    for model in hardware.MODELS:
        path = models_dir() / model["filename"]
        installed = path.exists() and path.stat().st_size > 1024
        out.append(
            ModelStatus(
                id=model["id"],
                kind=model["kind"],
                label=model["label"],
                size_gb=model["size_gb"],
                min_tier=model["min_tier"],
                speed=model["speed"],
                filename=model["filename"],
                installed=installed,
                active=str(path) in active_paths,
                fits=_fits(model["size_gb"]),
                path=str(path) if installed else "",
                tier_ok=_tier_rank(tier) >= _tier_rank(model["min_tier"]),
            )
        )
    return out


def find(model_id: str) -> dict | None:
    return next((m for m in hardware.MODELS if m["id"] == model_id), None)


def download(model_id: str, progress=None) -> dict:
    """Fetch one model into the app data directory, resuming a partial file."""
    model = find(model_id)
    if model is None:
        raise KeyError(f"unknown model: {model_id}")

    dest = models_dir() / model["filename"]
    if dest.exists() and dest.stat().st_size > 1024 and not (dest.with_suffix(dest.suffix + ".part").exists()):
        return _describe(model, dest, downloaded=False)

    def tick(fraction: float) -> None:
        if progress:
            progress("download", min(0.99, fraction), f"{model['filename']} {fraction * 100:.0f}%")

    path = hardware.download_model(model, models_dir(), progress=tick)
    _record_hash(path)
    if progress:
        progress("download", 1.0, "verifying")
    return _describe(model, path, downloaded=True)


def _record_hash(path: Path) -> None:
    """Record what we actually got.

    Upstream-pinned hashes are not in the manifest yet, so this cannot *verify*
    authenticity - but it detects a truncated or corrupted file on the next run,
    and it is the hook a pinned hash slots into.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    sidecar = path.with_suffix(path.suffix + ".sha256")
    sidecar.write_text(f"{digest.hexdigest()}  {path.name}\n", "utf-8")


def verify(path: Path) -> bool | None:
    """``True`` verified, ``False`` corrupt, ``None`` no recorded hash."""
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not sidecar.exists():
        return None
    expected = sidecar.read_text("utf-8").split()[0]
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def _describe(model: dict, path: Path, downloaded: bool) -> dict:
    return {
        "id": model["id"],
        "path": str(path),
        "filename": model["filename"],
        "bytes": path.stat().st_size if path.exists() else 0,
        "downloaded": downloaded,
    }


def activate(model_id: str) -> dict:
    """Make a model the active one for its kind, and persist that choice."""
    model = find(model_id)
    if model is None:
        raise KeyError(f"unknown model: {model_id}")
    key = ACTIVE_KEYS.get(model["kind"])
    if key is None:
        raise ValueError(f"model kind {model['kind']} cannot be activated")

    path = models_dir() / model["filename"]
    if not path.exists():
        raise FileNotFoundError("download the model before activating it")

    setattr(SETTINGS, key, str(path))
    save()

    warning = None
    if not _fits(model["size_gb"]):
        warning = (
            f"{model['label']} needs about {model['size_gb']} GB and only "
            f"{_available_gb():.1f} GB is free right now; runs may swap or fail."
        )
    return {"ok": True, "active": active(), "warning": warning}


def active() -> dict:
    return {
        "asr": SETTINGS.whisper_model_path,
        "vad": SETTINGS.vad_model_path,
        "llm": SETTINGS.llm_model_path,
        "whisper_cli": SETTINGS.whisper_cli,
        "llama_url": SETTINGS.llama_url,
    }


def save() -> Path:
    """Write settings back so activation survives a restart."""
    target = SETTINGS.data_dir / "config.json"
    payload = SETTINGS.to_json()
    payload["data_dir"] = str(SETTINGS.data_dir)
    target.write_text(json.dumps(payload, indent=2), "utf-8")
    return target


def summary() -> dict:
    # One probe: it shells out for GPU and memory info on Windows.
    profile = hardware.probe()
    tier = hardware.classify_tier(profile)
    items = statuses(tier)
    advice = hardware.advise(profile)
    return {
        "tier": tier,
        "models_dir": str(models_dir()),
        "available_gb": available_gb(),
        "reserve_gb": SETTINGS.hardware.reserve_ram_gb,
        "models": [item.to_dict() for item in items],
        "active": active(),
        "whisper_cli": hardware.find_whisper_cli([models_dir() / ".." / "bin"]),
        "asr_ready": bool(
            hardware.find_whisper_cli([models_dir() / ".." / "bin"])
            and any(item.installed for item in items if item.kind == "asr")
        ),
        "recommended": {
            "asr": (advice.get("asr") or {}).get("id"),
            "llm": (advice.get("llm_scoring") or {}).get("id"),
        },
    }
