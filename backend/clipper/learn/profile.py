"""Personal hook style profile.

Regenerated from before/after hook edits. Deliberately deterministic: the
statistics are exact and inspectable, and an optional LLM pass can rephrase
them later. Nothing here guesses - if you have not edited a hook yet, the
profile is empty and stays empty.
"""

from __future__ import annotations

import re
import statistics

EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")

MIN_EDITS = 5


def _stats(edits: list[dict]) -> dict:
    befores = [e["before"] for e in edits if e.get("before")]
    afters = [e["after"] for e in edits if e.get("after")]
    if not befores or not afters or len(befores) != len(afters):
        return {}
    deltas = [len(a.split()) - len(b.split()) for a, b in zip(afters, befores)]
    shortened = sum(1 for d in deltas if d < 0)
    emoji_off = sum(
        1 for a, b in zip(afters, befores) if EMOJI_RE.search(b) and not EMOJI_RE.search(a)
    )
    tags_off = sum(1 for a, b in zip(afters, befores) if "#" in b and "#" not in a)
    second_person = sum(1 for a in afters if re.search(r"\byou\b|\byour\b", a, re.I))
    ends_question = sum(1 for a in afters if a.strip().endswith("?"))
    return {
        "edits": len(edits),
        "mean_word_delta": round(statistics.fmean(deltas), 2),
        "shortened_rate": round(shortened / len(edits), 2),
        "mean_after_words": round(statistics.fmean(len(a.split()) for a in afters), 2),
        "emoji_removed_rate": round(emoji_off / len(edits), 2),
        "hashtag_removed_rate": round(tags_off / len(edits), 2),
        "second_person_rate": round(second_person / len(edits), 2),
        "ends_with_question_rate": round(ends_question / len(edits), 2),
    }


def format_profile(stats: dict) -> str:
    if not stats or stats.get("edits", 0) < MIN_EDITS:
        return ""
    lines: list[str] = []
    if stats["mean_word_delta"] < -1:
        lines.append(
            f"Shortens hooks by about {abs(stats['mean_word_delta']):.1f} words "
            f"(target ~{stats['mean_after_words']:.0f} words)."
        )
    elif stats["mean_word_delta"] > 1:
        lines.append(f"Expands hooks by about {stats['mean_word_delta']:.1f} words.")
    if stats["shortened_rate"] > 0.6:
        lines.append("Almost always trims hooks when editing.")
    if stats["emoji_removed_rate"] > 0.3:
        lines.append("Removes emoji from hooks.")
    if stats["hashtag_removed_rate"] > 0.3:
        lines.append("Removes hashtags from hooks.")
    if stats["second_person_rate"] > 0.5:
        lines.append("Prefers second-person framing ('you').")
    if stats["ends_with_question_rate"] > 0.4:
        lines.append("Often ends hooks on a question.")
    return "\n".join(lines)


def summarize(edits: list[dict]) -> dict:
    stats = _stats(edits)
    return {
        "stats": stats,
        "profile": format_profile(stats),
        "ready": bool(stats) and stats.get("edits", 0) >= MIN_EDITS,
    }
