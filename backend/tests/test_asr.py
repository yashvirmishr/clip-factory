import pytest

from clipper.domain import Word
from clipper.pipeline.asr import (
    StubASR,
    SubtitleASR,
    WhisperCppASR,
    clean_text,
    parse_timestamp,
    words_to_utterances,
)

SRT = """1
00:00:01,000 --> 00:00:04,000
Nobody has ever tried this before.

2
00:00:04,200 --> 00:00:07,000
Wait, why would you do that?

3
00:00:07,500 --> 00:00:09,000
That is insane.
"""

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
<00:00:01.000>Nobody <00:00:01.400>has <00:00:01.700>ever <00:00:02.100>tried <00:00:02.500>this.
"""


def test_parse_timestamp_handles_comma_and_dot():
    assert parse_timestamp("00:00:01,500") == pytest.approx(1.5)
    assert parse_timestamp("01:02:03.250") == pytest.approx(3723.25)


def test_clean_text_strips_whisper_markers():
    assert clean_text("[_BEG_] hello  world") == "hello world"
    assert clean_text("hello <b>there</b>") == "hello there"


def test_srt_import_produces_timed_words(tmp_path):
    path = tmp_path / "captions.srt"
    path.write_text(SRT, "utf-8")
    result = SubtitleASR(path).transcribe()
    assert result.backend == "subtitle-import"
    assert len(result.utterances) == 3
    first = result.utterances[0]
    assert first.text.startswith("Nobody")
    assert first.start == pytest.approx(1.0)
    assert first.end == pytest.approx(4.0)
    assert all(word.end >= word.start for word in first.words)
    assert result.utterances[1].question is True


def test_vtt_inline_word_timestamps_are_used(tmp_path):
    path = tmp_path / "captions.vtt"
    path.write_text(VTT, "utf-8")
    result = SubtitleASR(path).transcribe()
    words = [w for u in result.utterances for w in u.words]
    assert len(words) == 5
    assert [round(w.start, 2) for w in words] == [1.0, 1.4, 1.7, 2.1, 2.5]
    assert all(w.refined for w in words)


def test_words_to_utterances_splits_on_punctuation_and_gaps():
    words = [
        Word(text="Hello", start=0.0, end=0.3),
        Word(text="there.", start=0.4, end=0.9),
        Word(text="Then", start=3.0, end=3.3),
        Word(text="later.", start=3.4, end=3.9),
    ]
    utterances = words_to_utterances(words)
    assert len(utterances) == 2
    assert utterances[0].text == "Hello there."
    assert utterances[0].terminal is True


def test_stub_asr_is_deterministic_and_covers_duration():
    first = StubASR(seed=3).transcribe(duration=90.0)
    second = StubASR(seed=3).transcribe(duration=90.0)
    assert [u.text for u in first.utterances] == [u.text for u in second.utterances]
    assert first.utterances
    assert first.utterances[-1].end < 90.0


def test_whisper_command_enables_vad_flash_attention_and_token_json(tmp_path):
    model = tmp_path / "ggml-small.en.bin"
    model.write_bytes(b"stub")
    vad = tmp_path / "silero.bin"
    vad.write_bytes(b"stub")
    asr = WhisperCppASR("whisper-cli", str(model), str(vad), threads=6)
    cmd = asr.build_command(tmp_path / "a.wav", tmp_path / "out")
    joined = " ".join(cmd)
    assert "--vad" in cmd
    assert "-fa" in cmd
    assert "-oj" in cmd
    assert "-ml 1" in joined
    assert "-t 6" in joined
    assert str(vad) in cmd


def test_whisper_unavailable_without_model_file():
    assert WhisperCppASR("whisper-cli", "does/not/exist.bin").available() is False


def test_whisper_command_carries_language_and_translate(tmp_path):
    asr = WhisperCppASR("whisper-cli", "model.bin", "", "hi", 4, True)
    cmd = asr.build_command(tmp_path / "a.wav", tmp_path / "asr")
    assert cmd[cmd.index("-l") + 1] == "hi"
    assert "-tr" in cmd

    plain = WhisperCppASR("whisper-cli", "model.bin")
    plain_cmd = plain.build_command(tmp_path / "a.wav", tmp_path / "asr")
    assert "-tr" not in plain_cmd
    # whisper.cpp defaults to English; "auto" must be passed explicitly or
    # Detect automatically silently transcribes English.
    assert plain_cmd[plain_cmd.index("-l") + 1] == "auto"


def test_transcript_cache_is_language_and_mode_specific(tmp_path, monkeypatch):
    from clipper import service
    from clipper.domain import SourceInfo

    monkeypatch.setattr(service.SETTINGS, "artifacts_dir", lambda: tmp_path, raising=False)
    source = SourceInfo(
        id="s1", name="s", path=str(tmp_path / "s.mp4"), duration=60.0, size_bytes=1
    )
    english = service.transcript_cache_path(source, "en", False, None, "whisper.cpp")
    hindi = service.transcript_cache_path(source, "hi", False, None, "whisper.cpp")
    translated = service.transcript_cache_path(source, "hi", True, None, "whisper.cpp")
    stub = service.transcript_cache_path(source, "en", False, None, "stub")
    assert len({english.name, hindi.name, translated.name}) == 3
    assert ".hi." in hindi.name and ".tr." in translated.name
    # The engine is part of the key: a forced stub run must not read the real
    # transcript, and a real run must not read the stub's synthetic words.
    assert stub.name != english.name
    assert ".stub." in stub.name
