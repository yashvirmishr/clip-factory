"""Prompt construction.

The system prompt is kept byte-stable so ``cache_prompt`` in llama-server can
reuse its KV across the whole scoring batch - that is the difference between
paying prefill once and paying it forty times.
"""

from __future__ import annotations

from ..domain import WindowFeatures

SYSTEM_PROMPT = """You rank short-form clips cut from long livestreams.

You are given a transcript window with timestamps. Judge how well it would work
as a standalone 15-90 second vertical clip for TikTok, Shorts or Reels.

Rules:
- It must make sense to someone who never saw the stream.
- It must open with a reason to keep watching (question, number, claim, stakes).
- Prefer a window with a payoff: a result, a punchline, a reveal, a mistake.
- Penalise mid-thought starts, unresolved references ("this", "that thing"),
  housekeeping, sponsor reads, and anything that only makes sense with video.
- The hook is the on-screen text for the first 3 seconds. Max 12 words, no
  hashtags, no emoji, no quotes. It must be supported by the transcript.
- The title is a short editorial label, max 8 words.
- Score 0-100. Be strict: 80+ means you would post it yourself. Most windows
  deserve under 50.

Answer with the JSON object only."""


def build_user_prompt(
    text: str,
    start: float,
    end: float,
    features: WindowFeatures,
    exemplars: list[dict] | None = None,
    style_profile: str = "",
) -> str:
    parts: list[str] = []
    if style_profile:
        parts.append(f"Creator preferences:\n{style_profile}\n")
    if exemplars:
        lines = ["Past decisions on similar windows:"]
        for ex in exemplars:
            verdict = ex.get("action", "?")
            hook = ex.get("hook", "")
            snippet = (ex.get("text", "") or "")[:220]
            lines.append(f"- {verdict.upper()} (score {ex.get('score', '?')}): {snippet}")
            if hook:
                lines.append(f"  hook used: {hook}")
        parts.append("\n".join(lines) + "\n")
    parts.append(
        f"Window {int(start // 60):02d}:{int(start % 60):02d} - "
        f"{int(end // 60):02d}:{int(end % 60):02d} "
        f"({features.duration:.0f}s, {features.word_count} words, "
        f"{features.words_per_sec:.1f} words/s)\n"
    )
    parts.append(text.strip())
    parts.append("\nReturn the JSON judgement.")
    return "\n".join(parts)


def build_critique_prompt(text: str) -> str:
    return (
        "A clip was selected from a livestream. Decide whether it holds up.\n"
        "standalone = a viewer who missed the stream understands it.\n"
        "payoff = something is resolved, revealed or funny by the end.\n"
        "verdict = keep only if both are true.\n\n"
        f"TRANSCRIPT:\n{text.strip()}\n\nReturn the JSON verdict."
    )
