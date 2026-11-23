import pytest

from clipper.config import CaptionConfig
from clipper.domain import Word
from clipper.pipeline.caption.group import caption_stats, group_words


def words(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=e, prob=0.95) for t, s, e in spec]


def test_pages_respect_word_limit():
    many = words([(f"w{i}", i * 0.3, i * 0.3 + 0.28) for i in range(12)])
    pages = group_words(many, CaptionConfig(max_words=3, cps_limit=100))
    assert all(len(p.words) <= 3 for p in pages)
    assert sum(len(p.words) for p in pages) == 12


def test_gap_splits_a_page_even_when_short():
    spec = [
        ("hello", 0.0, 0.3),
        ("there", 0.35, 0.6),
        ("later", 3.0, 3.3),
        ("friend", 3.35, 3.6),
    ]
    pages = group_words(words(spec), CaptionConfig(max_words=6, gap_split_s=0.45, cps_limit=100))
    assert len(pages) == 2
    assert pages[0].text == "hello there"
    assert pages[1].text == "later friend"


def test_sentence_end_closes_a_page():
    spec = [
        ("Nobody", 0.0, 0.3),
        ("cares.", 0.3, 0.6),
        ("Then", 0.65, 0.9),
        ("what?", 0.9, 1.2),
    ]
    pages = group_words(words(spec), CaptionConfig(max_words=6, cps_limit=100))
    assert [p.text for p in pages] == ["Nobody cares.", "Then what?"]


def test_reading_speed_split_flags_and_separates():
    # 12 characters in 0.3 s is 40 cps - far over the limit.
    spec = [
        ("extraordinarily", 0.0, 0.2),
        ("long", 0.2, 0.4),
        ("sentence", 0.4, 0.6),
    ]
    cfg = CaptionConfig(max_words=6, cps_limit=12.0)
    pages = group_words(words(spec), cfg)
    assert len(pages) > 1
    assert any("cps" in w for p in pages for w in p.warnings)


def test_line_wrapping_respects_max_chars():
    from clipper.pipeline.caption.group import _wrap

    lines = _wrap(["word0", "word1", "word2", "word3"], max_chars=7, max_lines=2)
    assert lines
    assert all(len(line) <= 7 for line in lines)
    assert len(lines) <= 2


def test_over_length_input_splits_instead_of_clipping():
    spec = [(f"word{i}", i * 0.4, i * 0.4 + 0.35) for i in range(4)]
    pages = group_words(
        words(spec),
        CaptionConfig(max_words=8, max_chars_per_line=6, max_lines=1, cps_limit=100),
    )
    assert len(pages) > 1
    assert all(len(p.text) <= 6 for p in pages)


def test_zero_duration_word_is_repaired_not_shipped():
    # A degenerate word would flash for one frame; padding gives it readable time.
    pages = group_words(words([("hi", 1.0, 1.0)]), CaptionConfig(cps_limit=100))
    assert pages[0].duration > 0
    assert pages[0].end > pages[0].start
    assert not pages[0].warnings


def test_short_pages_are_merged_into_their_neighbour():
    # Three fast words that would otherwise become three flicker pages.
    spec = [("wait", 0.0, 0.08), ("what", 0.09, 0.17), ("happened", 0.18, 0.30)]
    cfg = CaptionConfig(max_words=4, cps_limit=100, min_page_s=0.35, gap_split_s=0.5)
    pages = group_words(words(spec), cfg)
    assert len(pages) == 1
    assert pages[0].text == "wait what happened"
    assert pages[0].duration >= 0.35


def test_merge_respects_the_word_budget():
    spec = [("a", 0.0, 0.1), ("b", 0.11, 0.2), ("c", 0.21, 0.3), ("d", 0.31, 0.4)]
    cfg = CaptionConfig(max_words=2, cps_limit=100, min_page_s=0.5, gap_split_s=0.5)
    pages = group_words(words(spec), cfg)
    assert all(len(p.words) <= 2 for p in pages)
    assert sum(len(p.words) for p in pages) == 4


def test_grouping_is_deterministic_and_sorted():
    spec = [("b", 1.0, 1.3), ("a", 0.0, 0.3)]
    first = group_words(words(spec))
    second = group_words(words(spec))
    assert [p.text for p in first] == [p.text for p in second]
    assert first[0].start < first[-1].start


def test_caption_stats_aggregate():
    pages = group_words(words([("one", 0.0, 0.4), ("two", 0.5, 0.9)]))
    stats = caption_stats(pages)
    assert stats["pages"] == len(pages)
    assert stats["mean_cps"] >= 0
    assert caption_stats([])["pages"] == 0
