"""Central configuration: paths, scoring weights, gate thresholds.

Everything tunable lives here so the pipeline modules stay pure and testable.
Values are overridable via ``CLIPPER_*`` environment variables or a
``config.json`` in the app data directory.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def app_data_dir() -> Path:
    base = os.environ.get("CLIPPER_DATA_DIR")
    if base:
        return Path(base)
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "ClipFactory"


@dataclass
class AudioConfig:
    sample_rate: int = 16_000
    frame_ms: int = 100
    fft_size: int = 2048
    # Excitement proxy: bursts of spectral flux with high zero-crossing rate.
    # Deliberately *not* called "laughter" - no model is involved.
    excitement_window_s: float = 2.0


@dataclass
class WindowConfig:
    target_s: float = 30.0
    min_s: float = 15.0
    max_s: float = 90.0
    stride_s: float = 5.0
    keep_multiplier: int = 3
    min_words: int = 25


@dataclass
class SignalWeights:
    """Fusion weights. Sum to 1.0 before the LLM blend."""

    audio: float = 0.28
    excitement: float = 0.14
    chat: float = 0.18
    speech: float = 0.24
    hook_lexicon: float = 0.16

    def normalised(self) -> dict[str, float]:
        total = self.audio + self.excitement + self.chat + self.speech + self.hook_lexicon
        if total <= 0:
            return {"audio": 0.2, "excitement": 0.2, "chat": 0.2, "speech": 0.2, "hook_lexicon": 0.2}
        return {
            "audio": self.audio / total,
            "excitement": self.excitement / total,
            "chat": self.chat / total,
            "speech": self.speech / total,
            "hook_lexicon": self.hook_lexicon / total,
        }


@dataclass
class BlendConfig:
    """How the deterministic fusion score combines with the LLM score."""

    signal_weight: float = 0.45
    llm_weight: float = 0.55
    # When the LLM is unavailable (stub scorer) the signal score carries fully.
    skip_llm_when_confident: float = 0.0


@dataclass
class GateConfig:
    min_words: int = 22
    min_asr_confidence: float = 0.55
    max_low_conf_ratio: float = 0.30
    min_speech_coverage: float = 0.40
    duration_min_s: float = 12.0
    duration_max_s: float = 95.0
    max_overlap_ratio: float = 0.20
    dedupe_cosine: float = 0.92
    hook_window_s: float = 3.0
    stream_warmup_s: float = 90.0
    max_non_latin_ratio: float = 0.15
    sponsor_keywords: tuple[str, ...] = (
        "sponsor",
        "sponsored by",
        "promo code",
        "use my code",
        "today's sponsor",
        "todays sponsor",
        "thanks to our sponsor",
        "link in the description",
        "check out the link",
    )
    blocklist: tuple[str, ...] = ()


@dataclass
class CaptionConfig:
    """Caption page grouping. Chars are counted without spaces."""

    max_words: int = 4
    min_words: int = 1
    max_chars_per_line: int = 22
    max_lines: int = 2
    cps_limit: float = 19.0
    gap_split_s: float = 0.45
    min_page_s: float = 0.35


@dataclass
class LearnConfig:
    """Feedback loop tuning."""

    min_decisions_for_ranker: int = 40
    retrain_every: int = 10
    few_shot_k: int = 3  # approved + rejected pairs
    style_profile_every: int = 20
    l2: float = 0.01
    lr: float = 0.05
    epochs: int = 400
    holdout_ratio: float = 0.25


@dataclass
class HardwareConfig:
    reserve_threads: int = 2
    reserve_ram_gb: float = 1.5
    whisper_model: str = ""  # auto
    llm_model: str = ""  # auto


@dataclass
class Settings:
    audio: AudioConfig = field(default_factory=AudioConfig)
    windows: WindowConfig = field(default_factory=WindowConfig)
    weights: SignalWeights = field(default_factory=SignalWeights)
    blend: BlendConfig = field(default_factory=BlendConfig)
    gates: GateConfig = field(default_factory=GateConfig)
    captions: CaptionConfig = field(default_factory=CaptionConfig)
    learn: LearnConfig = field(default_factory=LearnConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    data_dir: Path = field(default_factory=app_data_dir)
    # Whisper.cpp binary + model, resolved by the ASR backend at runtime.
    whisper_cli: str = ""
    whisper_model_path: str = ""
    vad_model_path: str = ""
    llama_url: str = ""

    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    def db_path(self) -> Path:
        return self.data_dir / "clipper.sqlite3"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.media_dir(), self.artifacts_dir()):
            p.mkdir(parents=True, exist_ok=True)

    def to_json(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        return d


def _apply_overrides(settings: Settings, raw: dict) -> Settings:
    for key, value in raw.items():
        section = getattr(settings, key, None)
        if section is None:
            continue
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, tuple):
                    v = tuple(v)
                if hasattr(section, k):
                    setattr(section, k, v)
        elif key == "data_dir":
            settings.data_dir = Path(value)
    return settings


def load_settings() -> Settings:
    settings = Settings()
    config_file = settings.data_dir / "config.json"
    if config_file.exists():
        try:
            _apply_overrides(settings, json.loads(config_file.read_text("utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    if os.environ.get("CLIPPER_LLAMA_URL"):
        settings.llama_url = os.environ["CLIPPER_LLAMA_URL"]
    if os.environ.get("CLIPPER_WHISPER_CLI"):
        settings.whisper_cli = os.environ["CLIPPER_WHISPER_CLI"]
    settings.ensure_dirs()
    # Absolute from here on: pipeline subprocesses run with their own cwd (the
    # renderer chdir's into the ASS directory), so a relative data dir resolves
    # against the wrong place and ffmpeg cannot open its output.
    settings.data_dir = settings.data_dir.resolve()
    return settings


SETTINGS = load_settings()
