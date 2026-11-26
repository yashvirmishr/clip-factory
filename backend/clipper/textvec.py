"""Deterministic, dependency-free text utilities.

Vectors are hashed word-bigram + char-4gram features. This is *lexical*
similarity, not semantics - it is used for near-duplicate rejection and for
few-shot exemplar retrieval, where lexical overlap is actually the right
signal and a 400 MB embedding model is not. Stable across runs because the
hash is blake2b, never Python's salted ``hash()``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

import numpy as np

from .lang import script_of as _script_of
from .lang import tokenize as _unicode_tokenize

DIM = 512

HOOK_WORDS: frozenset[str] = frozenset(
    """
    why how what never always everyone nobody nothing literally actually
    truth mistake wrong secret nobody insane crazy unreal huge massive
    finally worst best ever free money broke rich fail failed win won
    you your you're stop wait look listen imagine
    """.split()
)

SECOND_PERSON: frozenset[str] = frozenset("you your yours yourself you're youve".split())

PROFANITY: frozenset[str] = frozenset(
    "fuck fucking shit shitting damn hell ass bullshit crap".split()
)

# Words that make a clip's opening sentence fail to stand alone.
DEICTIC_OPENERS: frozenset[str] = frozenset(
    """
    this that these those it he she they them him her his hers its their
    there here then so and but because which what
    """.split()
)

FILLER: frozenset[str] = frozenset("um uh uhh umm er erm ah ahh like yknow".split())

TERMINAL_PUNCT = ".!?…"


def tokenize(text: str) -> list[str]:
    """Delegates to the Unicode tokenizer so non-Latin text is not invisible."""
    return _unicode_tokenize(text)


def _bucket(feature: str) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % DIM, 1.0 if (value >> 63) & 1 else -1.0


def vector(text: str, dim: int = DIM) -> np.ndarray:
    """L2-normalised hashed feature vector."""
    tokens = tokenize(text)
    if not tokens:
        return np.zeros(dim, dtype=np.float32)
    counts: dict[str, float] = {}
    for tok in tokens:
        counts[tok] = counts.get(tok, 0.0) + 1.0
    for a, b in zip(tokens, tokens[1:]):
        counts[f"{a}_{b}"] = counts.get(f"{a}_{b}", 0.0) + 1.0
    joined = " ".join(tokens)
    for i in range(len(joined) - 3):
        counts[f"#{joined[i:i + 4]}"] = counts.get(f"#{joined[i:i + 4]}", 0.0) + 0.5

    out = np.zeros(dim, dtype=np.float32)
    for feature, count in counts.items():
        idx, sign = _bucket(feature)
        out[idx] += sign * (1.0 + np.log(count))
    norm = float(np.linalg.norm(out))
    return out / norm if norm > 0 else out


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def hook_lexicon_hits(text: str) -> int:
    return sum(1 for t in tokenize(text) if t in HOOK_WORDS)


def count_tokens(text: str, vocab: frozenset[str]) -> int:
    return sum(1 for t in tokenize(text) if t in vocab)


def caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def starts_with_deictic(text: str) -> str | None:
    """Return the offending opener, or None if the sentence stands alone.

    The opener lists are English. Silently returning "fine" for other scripts is
    the honest answer: a Japanese sentence is not failing a check, it is simply
    not being checked by this one.
    """
    if _script_of(text) not in {"latin", "none"}:
        return None
    tokens = tokenize(text)
    if not tokens:
        return None
    first = tokens[0]
    if first in DEICTIC_OPENERS:
        return first
    # "and then he..." / "but the thing is" - leading conjunction chains.
    if first in {"and", "but", "because", "so", "then"} and len(tokens) > 1:
        return first
    return None


def first_sentence(text: str, max_chars: int = 160) -> str:
    match = re.search(r"[.!?…](?:\s|$)", text)
    sentence = text[: match.end()] if match else text
    return sentence.strip()[:max_chars]


def strip_fillers(words: Iterable[str]) -> list[str]:
    return [w for w in words if w.lower().strip(".,!?") not in FILLER]
