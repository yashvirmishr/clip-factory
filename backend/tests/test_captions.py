import pytest

from clipper.config import CaptionConfig
from clipper.domain import ClipCandidate, Word
from clipper.pipeline.caption import CaptionWord, edit_pages, pages_for
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


# ------------------------------------------------ manual caption editing


def clip_words() -> list[Word]:
    return [
        Word(text=text, start=index * 0.5, end=index * 0.5 + 0.4, prob=0.95)
        for index, text in enumerate(["one", "two", "three"])
    ]


def candidate() -> ClipCandidate:
    items = clip_words()
    return ClipCandidate(
        id="clip1",
        source_id="src1",
        start=0.0,
        end=10.0,
        text=" ".join(word.text for word in items),
        words=items,
    )


def test_edit_pages_normalises_text_and_spacing():
    pages = edit_pages(
        [[CaptionWord(text="  hello ", start=1.0, end=1.4),
          CaptionWord(text="world", start=1.5, end=1.9)]],
        0.0,
        10.0,
    )
    assert len(pages) == 1
    assert pages[0].text == "hello world"
    assert pages[0].lines == ["hello world"]
    assert pages[0].start == 1.0
    assert pages[0].end == 1.9


def test_edit_pages_keeps_manual_page_splits():
    pages = edit_pages(
        [
            [CaptionWord(text="one", start=0.0, end=0.4),
             CaptionWord(text="two", start=0.5, end=0.9)],
            [CaptionWord(text="three", start=1.0, end=1.4)],
        ],
        0.0,
        10.0,
    )
    assert [page.text for page in pages] == ["one two", "three"]
    assert [page.index for page in pages] == [0, 1]


def test_edit_pages_clips_words_at_the_clip_edges():
    pages = edit_pages(
        [[CaptionWord(text="edge", start=-1.0, end=0.5),
          CaptionWord(text="end", start=9.6, end=12.0)]],
        0.0,
        10.0,
    )
    assert pages[0].words[0].start == 0.0
    assert pages[0].words[-1].end == 10.0


def test_edit_pages_rejects_overlapping_pages():
    with pytest.raises(ValueError, match="pages overlap"):
        edit_pages(
            [
                [CaptionWord(text="one", start=1.0, end=3.0)],
                [CaptionWord(text="two", start=2.0, end=4.0)],
            ],
            0.0,
            10.0,
        )


def test_edit_pages_rejects_a_word_outside_the_clip():
    with pytest.raises(ValueError, match="outside the clip"):
        edit_pages([[CaptionWord(text="gone", start=0.0, end=0.5)]], 5.0, 10.0)


def test_edit_pages_rejects_empty_pages_and_non_finite_words():
    with pytest.raises(ValueError, match="at least one"):
        edit_pages([], 0.0, 10.0)
    with pytest.raises(ValueError, match="no words"):
        edit_pages([[]], 0.0, 10.0)
    with pytest.raises(ValueError, match="non-finite"):
        edit_pages([[CaptionWord(text="x", start=float("nan"), end=1.0)]], 0.0, 10.0)


def test_pages_for_prefers_a_valid_override():
    clip = candidate()
    edited = edit_pages([[CaptionWord(text="fixed", start=1.0, end=2.0)]], 0.0, 10.0)
    clip.caption_pages = [page.model_dump() for page in edited]
    assert [page.text for page in pages_for(clip)] == ["fixed"]


def test_pages_for_falls_back_when_the_override_is_corrupt():
    clip = candidate()
    clip.caption_pages = [{"text": 3}]
    assert pages_for(clip) == group_words(clip.words)
