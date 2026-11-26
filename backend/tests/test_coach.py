import pytest

from clipper import coach
from clipper.domain import ClipCandidate, LLMJudgement, WindowFeatures, Word


def candidate():
    words = [
        Word(text="So", start=1.0, end=1.2),
        Word(text="this", start=1.2, end=1.4),
        Word(text="is", start=1.4, end=1.5),
        Word(text="the", start=1.5, end=1.6),
        Word(text="setup.", start=1.6, end=1.8),
        Word(text="and", start=1.8, end=1.9),
        Word(text="then", start=1.9, end=2.0),
    ]
    return ClipCandidate(
        id="clip1", source_id="source1", start=0.0, end=3.0,
        text="So this is the setup. and then", words=words,
        features=WindowFeatures(
            duration=3.0, word_count=7, words_per_sec=2.3,
            speech_coverage=0.9, mean_word_prob=0.9,
        ),
        llm=LLMJudgement(score=60, hook="", has_payoff=True),
        final=0.5,
    )


def test_generate_cites_a_timestamp_and_quote(clean_db):
    items = coach.generate(candidate())
    kinds = {item["kind"] for item in items}
    assert "dead_air_start" in kinds
    assert "mid_sentence_end" in kinds
    dead = next(item for item in items if item["kind"] == "dead_air_start")
    evidence = dead["evidence"][0]
    assert evidence["start"] == 0.0
    assert evidence["end"] == 1.0
    assert evidence["quote"].startswith("So this")
    assert evidence["metric"] == "lead_in_s"
    assert dead["auto_fixable"] is True


def test_preview_never_mutates_the_clip(clean_db):
    clip = candidate()
    item = next(item for item in coach.refresh(clip) if item["kind"] == "dead_air_start")
    shown = coach.preview(clip, item)
    assert shown["after"]["start"] == 1.0
    assert shown["after_text"].startswith("So this")
    assert clip.start == 0.0
    assert clip.text.startswith("So this")


def test_apply_then_undo_restores_trim(clean_db):
    clip = candidate()
    item = next(item for item in coach.refresh(clip) if item["kind"] == "dead_air_start")

    def trim(start, end):
        clip.start, clip.end = start, end
        return clip

    applied = coach.apply("source1", "clip1", item["id"], trim_fn=trim, candidate=clip)
    assert applied["changed"] is True
    assert clip.start == 1.0
    assert coach.get(item["id"])["status"] == "applied"
    coach.undo("source1", "clip1", item["id"], trim_fn=trim)
    assert clip.start == 0.0
    assert coach.get(item["id"])["status"] == "open"


def test_manual_only_suggestion_cannot_be_applied(clean_db):
    clip = candidate()
    item = next(item for item in coach.refresh(clip) if item["kind"] == "weak_hook")
    with pytest.raises(ValueError, match="manual"):
        coach.apply("source1", "clip1", item["id"], trim_fn=lambda s, e: clip, candidate=clip)


def test_a_fixed_condition_is_resolved_instead_of_staying_open(clean_db):
    clip = candidate()
    item = next(item for item in coach.refresh(clip) if item["kind"] == "dead_air_start")
    clip.start = 1.0
    rows = coach.refresh(clip)
    assert item["id"] not in {row["id"] for row in rows if row["status"] == "open"}
    assert coach.get(item["id"])["status"] == "resolved"


def test_dismiss_hides_from_the_open_list(clean_db):
    clip = candidate()
    item = next(item for item in coach.refresh(clip) if item["kind"] == "weak_hook")
    coach.dismiss(item["id"])
    assert item["id"] not in {row["id"] for row in coach.list_for_clip("source1", "clip1", include_closed=False)}
