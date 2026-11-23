import numpy as np

from clipper.textvec import (
    caps_ratio,
    cosine,
    hook_lexicon_hits,
    starts_with_deictic,
    strip_fillers,
    tokenize,
    vector,
)


def test_vector_is_normalised_and_stable():
    a = vector("nobody has actually tried this before")
    b = vector("nobody has actually tried this before")
    assert np.isclose(np.linalg.norm(a), 1.0)
    assert np.allclose(a, b)
    assert cosine(a, b) > 0.999


def test_empty_text_is_zero_vector():
    v = vector("")
    assert np.linalg.norm(v) == 0.0
    assert cosine(v, vector("hello")) == 0.0


def test_related_texts_score_higher_than_unrelated():
    base = vector("I died in the first thirty seconds of the run")
    related = vector("the run started and I died in thirty seconds")
    unrelated = vector("sponsorship rates are up this quarter for everyone")
    assert cosine(base, related) > cosine(base, unrelated)


def test_deictic_opener_detection():
    assert starts_with_deictic("This is the craziest thing") == "this"
    assert starts_with_deictic("And then he just walked away") == "and"
    assert starts_with_deictic("Nobody has ever done this") is None


def test_caps_and_lexicon():
    assert caps_ratio("WHY would you DO that") > 0.25
    assert caps_ratio("EVERYTHING IS FINE") == 1.0
    assert hook_lexicon_hits("why would you never do this") >= 3
    assert tokenize("Hello, world! 42") == ["hello", "world", "42"]


def test_filler_stripping():
    assert strip_fillers(["um", "hello", "uh", "world"]) == ["hello", "world"]
