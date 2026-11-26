"""Speech recognition backends.

Three interchangeable sources of word-level timings:

* ``WhisperCppASR``  - bundled ``whisper-cli`` (Vulkan / CUDA / CPU, VAD on).
* ``SubtitleASR``    - import an existing ``.srt`` / ``.vtt``; no model needed.
* ``StubASR``        - deterministic synthetic transcript, so the whole pipeline
                       and UI are exercisable before any model is downloaded.

All three return the same ``list[Utterance]``; nothing downstream knows which
one ran.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..domain import Utterance, Word

_TS_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})"
)
_VTT_INLINE_RE = re.compile(r"<(\d{2}):(\d{2}):(\d{2})\.(\d{3})>")
_TAG_RE = re.compile(r"\[_[A-Z0-9_]+\]|<[^>]+>|\{[^}]*\}")


class ASRError(RuntimeError):
    pass


@dataclass
class ASRResult:
    utterances: list[Utterance]
    backend: str
    language: str = "en"


def _ts_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_timestamp(text: str) -> float | None:
    match = _TS_RE.search(text)
    if not match:
        return None
    return _ts_to_seconds(match["h"], match["m"], match["s"], match["ms"])


def clean_text(text: str) -> str:
    text = _TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def split_words_proportional(start: float, end: float, text: str) -> list[Word]:
    """Even-ish split of a cue into words, weighted by length.

    Cue-level subtitles have no word timing; this is an estimate and is marked
    ``refined=False`` so the caption layer knows it may need snapping.
    """
    tokens = clean_text(text).split()
    if not tokens:
        return []
    weights = [len(t) + 1 for t in tokens]
    total = sum(weights)
    span = max(0.05, end - start)
    cursor = start
    words: list[Word] = []
    for token, weight in zip(tokens, weights):
        dur = span * weight / total
        words.append(Word(text=token, start=cursor, end=cursor + dur, prob=0.9, refined=False))
        cursor += dur
    return words


def words_to_utterances(
    words: list[Word], max_gap: float = 1.0, max_s: float = 14.0, max_words: int = 42
) -> list[Utterance]:
    """Group words into sentence-ish units used for windows and captions."""
    if not words:
        return []
    words = sorted(words, key=lambda w: w.start)
    groups: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current:
            gap = word.start - current[-1].end
            span = word.end - current[0].start
            if gap > max_gap or span > max_s or len(current) >= max_words:
                groups.append(current)
                current = []
        current.append(word)
        if word.text.rstrip().endswith((".", "!", "?", "…")):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    utterances: list[Utterance] = []
    for group in groups:
        text = " ".join(w.text for w in group).strip()
        if not text:
            continue
        terminal = text.endswith((".", "!", "?", "…"))
        utterances.append(
            Utterance(
                start=group[0].start,
                end=group[-1].end,
                text=text,
                words=group,
                question=text.endswith("?"),
                terminal=terminal,
            )
        )
    return utterances


class SubtitleASR:
    """Import SRT or VTT. Uses inline VTT word timestamps when present."""

    name = "subtitle-import"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def available(self) -> bool:
        return self.path.exists()

    def _words_from_vtt_body(self, body: str) -> list[Word]:
        """Split a cue body on inline ``<hh:mm:ss.mmm>`` markers.

        Each marker starts the following run of text, so ``<t0>Nobody <t1>has``
        yields 'Nobody' from t0 to t1 and 'has' from t1 onwards.
        """
        marks = list(_VTT_INLINE_RE.finditer(body))
        if not marks:
            return []
        words: list[Word] = []
        for index, mark in enumerate(marks):
            start = _ts_to_seconds(mark.group(1), mark.group(2), mark.group(3), mark.group(4))
            next_mark = marks[index + 1] if index + 1 < len(marks) else None
            segment_end = next_mark.start() if next_mark else len(body)
            if next_mark:
                end = _ts_to_seconds(
                    next_mark.group(1), next_mark.group(2), next_mark.group(3), next_mark.group(4)
                )
            else:
                end = start + 0.3
            tokens = clean_text(body[mark.end():segment_end]).split()
            if not tokens:
                continue
            per = max(0.04, (max(start + 0.05, end) - start) / len(tokens))
            for offset, token in enumerate(tokens):
                word_start = start + offset * per
                words.append(
                    Word(text=token, start=round(word_start, 3), end=round(word_start + per, 3), refined=True)
                )
        return words

    def transcribe(self) -> ASRResult:
        raw = self.path.read_text("utf-8-sig", errors="replace")
        blocks = re.split(r"\r?\n\r?\n+", raw.strip())
        words: list[Word] = []
        for block in blocks:
            lines = [ln for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
            if timing_idx is None:
                continue
            left, _, right = lines[timing_idx].partition("-->") 
            start = parse_timestamp(left)
            end = parse_timestamp(right)
            if start is None or end is None:
                continue
            body = "\n".join(lines[timing_idx + 1 :])
            inline = self._words_from_vtt_body(body)
            if inline:
                words.extend(inline)
            else:
                words.extend(split_words_proportional(start, end, body))
        if not words:
            raise ASRError(f"No subtitle cues found in {self.path.name}")
        return ASRResult(words_to_utterances(words), self.name)


class WhisperCppASR:
    """Bundled whisper.cpp CLI. VAD on by default: it both speeds up streams and
    prevents the documented music/silence hallucination class."""

    name = "whisper.cpp"

    def __init__(
        self,
        cli: str,
        model_path: str,
        vad_model_path: str = "",
        language: str = "auto",
        threads: int = 0,
        translate: bool = False,
    ) -> None:
        self.cli = cli
        self.model_path = model_path
        self.vad_model_path = vad_model_path
        self.language = language
        self.threads = threads
        # whisper.cpp can only translate *into* English (-tr). It is not a
        # general translator, and the UI must not pretend otherwise.
        self.translate = translate

    def available(self) -> bool:
        if not self.cli:
            return False
        resolved = shutil.which(self.cli) or (self.cli if Path(self.cli).exists() else "")
        if not resolved:
            return False
        return bool(self.model_path) and Path(self.model_path).exists()

    def build_command(self, wav: Path, out_prefix: Path) -> list[str]:
        cmd = [
            self.cli,
            "-m", self.model_path,
            "-f", str(wav),
            "-ml", "1",
            "-oj",
            "-of", str(out_prefix),
            "-np",
            "-fa",
        ]
        if self.vad_model_path and Path(self.vad_model_path).exists():
            cmd += [
                "--vad", "-vm", self.vad_model_path,
                "-vt", "0.5",
                "-vsd", "500",
                "-vp", "30",
            ]
        # whisper.cpp defaults to English, so "auto" has to be asked for by
        # name; omitting -l makes Detect automatically transcribe English.
        if self.language:
            cmd += ["-l", self.language]
        if self.translate:
            cmd += ["-tr"]
        if self.threads > 0:
            cmd += ["-t", str(self.threads)]
        return cmd

    def transcribe(self, wav: str | Path, work_dir: str | Path) -> ASRResult:
        wav = Path(wav)
        out_prefix = Path(work_dir) / "asr"
        cmd = self.build_command(wav, out_prefix)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=24 * 3600)
        except FileNotFoundError as exc:
            raise ASRError(f"whisper-cli not found at {self.cli!r}") from exc
        if proc.returncode != 0:
            raise ASRError(f"whisper-cli failed: {proc.stderr.strip()[:500]}")
        json_path = Path(str(out_prefix) + ".json")
        if not json_path.exists():
            raise ASRError("whisper-cli produced no JSON output")
        payload = json.loads(json_path.read_text("utf-8"))
        detected = str((payload.get("result") or {}).get("language") or "").strip()
        if not detected and self.language and self.language != "auto":
            detected = self.language

        words: list[Word] = []
        for seg in payload.get("transcription", []):
            text = clean_text(seg.get("text", ""))
            offsets = seg.get("offsets") or {}
            start = float(offsets.get("from", 0)) / 1000.0
            end = float(offsets.get("to", 0)) / 1000.0
            seg_words = split_words_proportional(start, end, text) if text else []
            for w in seg_words:
                w.refined = True
            words.extend(seg_words)
        return ASRResult(words_to_utterances(words), self.name, detected or "en")


_STUB_LINES = [
    "Okay so nobody has actually tried this before, which is exactly why we should.",
    "I died in the first thirty seconds. There is no coming back from that.",
    "Wait, wait. Say that again but slowly, because that does not sound legal.",
    "This is the part where chat always tells me to stop and I never listen.",
    "The trick is you have to unplug it before it finishes the update.",
    "Everyone said it was impossible and honestly they were completely right.",
    "Here is the thing about money. It is not real and that is the whole problem.",
    "How do speedrunners find this in under four seconds?",
    "I have been doing this for six hours and the room still looks terrible.",
    "Can we talk about the fact that the last three runs were all faster?",
    "You will not believe what happened next. I still do not believe it.",
    "Three hundred people watched me fail that input live on stream.",
    "The developer actually replied to my post and called out the exact bug.",
    "Never trust an autosave that happens while the game is lagging.",
    "Best run of the night and of course the recording dropped a frame.",
    "So the plan is simple. We break it, we buy it, we pretend it was always broken.",
]


class StubASR:
    """Deterministic synthetic transcript for tests and for ``--demo`` mode."""

    name = "stub"

    def __init__(self, seed: int = 7) -> None:
        self.seed = seed

    def available(self) -> bool:
        return True

    def transcribe(
        self, duration: float = 600.0, mask: object | None = None
    ) -> ASRResult:
        words: list[Word] = []
        cursor = 4.0
        i = 0
        while cursor < duration - 6.0:
            line = _STUB_LINES[(i * 5 + self.seed) % len(_STUB_LINES)]
            tokens = line.split()
            per = 0.34
            for token in tokens:
                words.append(
                    Word(text=token, start=cursor, end=cursor + per, prob=0.94, refined=False)
                )
                cursor += per + 0.02
            cursor += 1.4
            i += 1
        return ASRResult(words_to_utterances(words), self.name)


def resolve_backend(
    *,
    whisper_cli: str = "",
    whisper_model: str = "",
    vad_model: str = "",
    subtitle_path: str | Path | None = None,
    threads: int = 0,
    language: str = "auto",
    translate: bool = False,
) -> object:
    """Prefer real ASR, fall back to subtitle import, never crash."""
    whisper = WhisperCppASR(
        whisper_cli, whisper_model, vad_model, language, threads, translate
    )
    if whisper.available():
        return whisper
    if subtitle_path and Path(subtitle_path).exists():
        return SubtitleASR(subtitle_path)
    return StubASR()
