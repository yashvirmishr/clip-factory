import numpy as np
import pytest
from dataclasses import replace

from clipper.config import GateConfig, SignalWeights, WindowConfig
from clipper.domain import ClipCandidate, Utterance, Word, WindowFeatures
from clipper.pipeline.align import refine_words
from clipper.pipeline.gates import evaluate_gates, hook_cue, non_latin_ratio
from clipper.pipeline.media import AudioAnalysis
from clipper.pipeline.scorecard import grounding_ratio
from clipper.pipeline.select import select_clips
from clipper.pipeline.signals import fuse, normalise_signals, percentile_rank
from clipper.pipeline.windows import build_windows


def make_analysis(frames: int = 2000, frame_rate: float = 10.0) -> AudioAnalysis:
    return AudioAnalysis(
        frame_rate=frame_rate,
        rms=np.full(frames, 0.2, dtype=np.float32),
        flux=np.zeros(frames, dtype=np.float32),
        zcr=np.zeros(frames, dtype=np.float32),
        mask=np.ones(frames, dtype=bool),
        duration=frames / frame_rate,
    )


def make_utterances(count: int, step: float = 5.0) -> list[Utterance]:
    out: list[Utterance] = []
    for i in range(count):
        start = i * step
        words = [
            Word(text="word", start=start + 0.1, end=start + 1.0, prob=0.95),
            Word(text="more", start=start + 1.2, end=start + 2.2, prob=0.95),
            Word(text="text.", start=start + 2.4, end=start + 3.4, prob=0.95),
        ]
        out.append(
            Utterance(start=start, end=start + step - 0.2, text="word more text.", words=words, terminal=True)
        )
    return out


# ---------------------------------------------------------------- windows
def test_windows_respect_duration_bounds_and_boundaries():
    utterances = make_utterances(30)
    windows = build_windows(utterances, WindowConfig())
    assert windows
    starts = {round(u.start, 3) for u in utterances}
    ends = {round(u.end, 3) for u in utterances}
    for window in windows:
        assert 15.0 <= window.duration <= 90.0
        assert round(window.start, 3) in starts
        assert round(window.end, 3) in ends


def test_windows_empty_input():
    assert build_windows([], WindowConfig()) == []


# ---------------------------------------------------------------- signals
def test_percentile_rank_is_monotonic():
    values = np.array([5.0, 1.0, 9.0, 3.0], dtype=np.float32)
    ranks = percentile_rank(values)
    assert ranks.max() == pytest.approx(1.0)
    assert ranks.min() == pytest.approx(0.0)
    assert np.argmax(values) == np.argmax(ranks)


def test_percentile_rank_flat_input_is_neutral():
    ranks = percentile_rank(np.ones(5, dtype=np.float32))
    assert np.allclose(ranks, 0.5)


def test_missing_chat_signal_redistributes_weight():
    raw = {
        "audio": [1.0, 2.0],
        "excitement": [1.0, 2.0],
        "chat": [0.0, 5.0],
        "speech": [1.0, 2.0],
        "hook_lexicon": [1.0, 2.0],
    }
    all_signals = normalise_signals(raw, set(raw))
    no_chat = normalise_signals(raw, {"audio", "excitement", "speech", "hook_lexicon"})
    assert all_signals[1]["chat"] == 1.0
    assert no_chat[1]["chat"] == 0.0

    weights = SignalWeights()
    with_chat = fuse({"audio": 1, "excitement": 1, "chat": 0, "speech": 1, "hook_lexicon": 1}, weights, set(raw))
    without_chat = fuse(
        {"audio": 1, "excitement": 1, "chat": 0, "speech": 1, "hook_lexicon": 1},
        weights,
        {"audio", "excitement", "speech", "hook_lexicon"},
    )
    assert without_chat > with_chat
    assert without_chat == pytest.approx(1.0)


# ------------------------------------------------------------------ gates
def test_hook_cue_detection():
    assert hook_cue("Why would anyone do this") == "why_how_what"
    assert hook_cue("I lost 400 dollars") == "number"
    assert hook_cue("you are going to love this") == "second_person"
    assert hook_cue("the weather is mild today") is None


def test_non_latin_ratio_flags_hallucination():
    assert non_latin_ratio("これはテストです") > 0.9
    assert non_latin_ratio("hello there friend") == 0.0


def _gates_for(text: str, *, duration: float = 30.0, start: float = 120.0, expected_script: str = ""):
    cfg = GateConfig()
    words = [Word(text=w, start=start + i * 0.3, end=start + i * 0.3 + 0.25, prob=0.95) for i, w in enumerate(text.split())]
    base = build_windows(make_utterances(10), WindowConfig())[0]
    window = replace(base, start=start, end=start + duration, text=text, last_terminal=True)
    features = WindowFeatures(
        duration=duration,
        word_count=len(text.split()),
        words_per_sec=len(text.split()) / duration,
        mean_word_prob=0.95,
        low_conf_ratio=0.0,
        speech_coverage=0.9,
        start_in_stream=start,
        end_in_stream=start + duration,
    )
    return {
        g.id: g
        for g in evaluate_gates(
            window, features, words, cfg, stream_duration=3600.0,
            expected_script=expected_script,
        )
    }


def test_sponsor_read_is_blocked():
    gates = _gates_for("today's sponsor is the best vpn, use my code for a discount on the whole thing")
    assert gates["not_sponsor"].passed is False


def test_hallucinated_script_is_blocked():
    gates = _gates_for("これはテストです これはテストです これはテストです")
    assert gates["not_hallucinated"].passed is False


def test_a_japanese_window_is_not_a_hallucination_when_japanese_was_asked_for():
    gates = _gates_for("これはテストです これはテストです", expected_script="kana")
    assert gates["not_hallucinated"].passed
    # Without an English lexicon the hook gate may only flag, never block.
    assert gates["hook_in_first_seconds"].severity == "warn"


def test_a_mixed_script_window_only_warns():
    gates = _gates_for("this is ここれはテストです", expected_script="latin")
    assert gates["not_hallucinated"].severity == "warn"
    assert gates["not_hallucinated"].passed is False


def test_clean_window_passes_input_gates():
    gates = _gates_for("why would you never do this to your own setup honestly")
    assert gates["asr_confidence"].passed
    assert gates["not_hallucinated"].passed
    assert gates["not_sponsor"].passed
    assert gates["hook_in_first_seconds"].passed


# ------------------------------------------------------------------ align
def test_refine_words_enforces_monotonic_timings():
    words = [
        Word(text="a", start=1.0, end=2.0),
        Word(text="b", start=1.5, end=1.6),  # overlaps and goes backwards
        Word(text="c", start=1.55, end=9.0),  # absurd duration
    ]
    refined = refine_words(words, make_analysis())
    for previous, current in zip(refined, refined[1:]):
        assert current.start >= previous.start
        assert current.end >= current.start
    assert all(w.duration <= 9.0 for w in refined)


def test_refine_words_does_not_drift_on_flat_audio():
    words = [Word(text="a", start=5.0, end=5.5), Word(text="b", start=5.6, end=6.1)]
    refined = refine_words(words, make_analysis())
    assert refined[0].start == pytest.approx(5.0, abs=0.05)


def test_refine_words_snaps_to_energy_trough():
    frames = 4000
    rms = np.full(frames, 0.5, dtype=np.float32)
    rms[990] = 0.001  # trough at 9.9 s with frame_rate 100
    analysis = AudioAnalysis(
        frame_rate=100.0, rms=rms, flux=np.zeros(frames, np.float32),
        zcr=np.zeros(frames, np.float32), mask=np.ones(frames, bool), duration=40.0,
    )
    refined = refine_words([Word(text="a", start=10.0, end=10.6)], analysis)
    assert refined[0].start == pytest.approx(9.9, abs=0.02)


# --------------------------------------------------------------- select
def _candidate(cid: str, start: float, end: float, final: float, text: str) -> ClipCandidate:
    return ClipCandidate(
        id=cid, source_id="src", start=start, end=end, text=text, fused=final, final=final
    )


def test_overlapping_candidates_are_deduplicated():
    a = _candidate("a", 0.0, 30.0, 0.9, "the first moment about a broken controller")
    b = _candidate("b", 5.0, 35.0, 0.8, "another moment about a broken controller")
    c = _candidate("c", 120.0, 150.0, 0.7, "a completely different moment about the chat")
    selected, dropped = select_clips([a, b, c], GateConfig(), limit=5)
    assert [s.id for s in selected] == ["a", "c"]
    assert any("no_overlap" in [g.id for g in d.gates] for d in dropped)


def test_near_duplicate_text_is_rejected():
    text = "nobody has ever tried this trick before and it works every single time"
    a = _candidate("a", 0.0, 30.0, 0.9, text)
    b = _candidate("b", 200.0, 230.0, 0.85, text)
    selected, dropped = select_clips([a, b], GateConfig(), limit=5)
    assert len(selected) == 1
    assert dropped and any("not_duplicate" in [g.id for g in d.gates] for d in dropped)


def test_ranks_are_sequential_and_limited():
    items = [_candidate(f"c{i}", i * 100.0, i * 100.0 + 30.0, 1.0 - i / 100, f"moment number {i}") for i in range(6)]
    selected, _ = select_clips(items, GateConfig(), limit=3)
    assert [s.rank for s in selected] == [1, 2, 3]


# --------------------------------------------------------------- scorecard
def test_grounding_ratio_requires_support():
    text = "I lost four hundred dollars on this bet at the casino"
    assert grounding_ratio("I lost dollars", text) >= 0.7
    assert grounding_ratio("alien spacecraft landed", text) < 0.3
    assert grounding_ratio("lost 900 dollars", text) < 0.7
