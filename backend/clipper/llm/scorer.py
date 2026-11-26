"""Scoring backends.

``LlamaServerScorer`` talks to llama.cpp's OpenAI-compatible endpoint with a
GBNF grammar so the response is always parseable, and keeps the system prompt
byte-stable so ``cache_prompt`` reuses its KV for the whole batch.

``HeuristicScorer`` is not a fallback pretending to be a model - it is a
deterministic stand-in that makes the app usable before a model is downloaded,
and labels itself as such everywhere it surfaces.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from ..domain import LLMJudgement, WindowFeatures
from ..textvec import starts_with_deictic
from .grammar import CRITIQUE_GRAMMAR, GRAMMAR
from .prompts import SYSTEM_PROMPT, build_critique_prompt, build_user_prompt

MAX_HOOK_WORDS = 12


class Scorer(Protocol):
    name: str

    def available(self) -> bool: ...

    def score(
        self,
        text: str,
        start: float,
        end: float,
        features: WindowFeatures,
        exemplars: list[dict] | None = None,
        style_profile: str = "",
    ) -> LLMJudgement: ...

    def critique(self, text: str) -> dict | None: ...


def _clip_words(text: str, limit: int) -> str:
    words = text.split()
    trimmed = " ".join(words[:limit]).strip(" ,;:-")
    trimmed = re.sub(r"[\"'“”]", "", trimmed)
    return trimmed[:80]


class HeuristicScorer:
    name = "heuristic-stub"

    def available(self) -> bool:
        return True

    def score(
        self,
        text: str,
        start: float,
        end: float,
        features: WindowFeatures,
        exemplars: list[dict] | None = None,
        style_profile: str = "",
    ) -> LLMJudgement:
        score = 34.0
        cues: list[str] = []
        if features.question_count:
            score += 9
            cues.append("question")
        if features.number_count:
            score += 7
            cues.append("number")
        if features.second_person:
            score += min(10, features.second_person * 3)
            cues.append("second-person")
        if features.hook_lexicon_hits:
            score += min(12, features.hook_lexicon_hits * 4)
            cues.append("hook-words")
        if features.exclaim_count:
            score += 4
            cues.append("exclamation")
        score += min(14, features.words_per_sec * 2.4)
        if features.speech_coverage < 0.55:
            score -= 12
            cues.append("sparse-speech")
        if starts_with_deictic(text):
            score -= 16
            cues.append("weak-open")
        if exemplars:
            approvals = sum(1 for e in exemplars if e.get("action") == "approve")
            score += (approvals - len(exemplars) + approvals) * 1.5

        score = int(max(0, min(100, round(score))))
        first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
        hook = _clip_words(first, MAX_HOOK_WORDS) or text[:60]
        title = _clip_words(first, 8) or "Untitled clip"
        reason = "stub scorer (no model installed): " + (", ".join(cues) or "no cues")
        return LLMJudgement(
            score=score,
            hook=hook,
            title=title,
            reason=reason,
            understands_standalone=starts_with_deictic(text) is None,
            has_payoff=features.exclaim_count > 0 or "?" in text,
            provider=self.name,
        )

    def critique(self, text: str) -> dict | None:
        standalone = starts_with_deictic(text) is None
        payoff = any(marker in text.lower() for marker in (" so ", " then ", " finally", " turns out")) or "?" in text
        return {
            "standalone": standalone,
            "payoff": payoff,
            "verdict": "keep" if standalone and payoff else "drop",
            "note": "heuristic critique",
        }


class LlamaServerScorer:
    name = "llama-server"

    def __init__(self, base_url: str, timeout: float = 120.0, max_tokens: int = 96) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens

    def available(self) -> bool:
        if not self.base_url:
            return False
        try:
            response = httpx.get(f"{self.base_url}/v1/models", timeout=3.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _chat(self, system: str, user: str, grammar: str) -> dict | None:
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": self.max_tokens,
            "cache_prompt": True,
            "grammar": grammar,
            "stream": False,
        }
        for attempt in (0, 1):
            body = dict(payload)
            if attempt == 1:
                body.pop("grammar", None)  # older builds reject unknown fields
                body["response_format"] = {"type": "json_object"}
            try:
                response = httpx.post(
                    f"{self.base_url}/v1/chat/completions", json=body, timeout=self.timeout
                )
            except httpx.HTTPError:
                return None
            if response.status_code != 200:
                continue
            try:
                content = response.json()["choices"][0]["message"]["content"]
                return json.loads(content)
            except (KeyError, IndexError, json.JSONDecodeError):
                continue
        return None

    def score(
        self,
        text: str,
        start: float,
        end: float,
        features: WindowFeatures,
        exemplars: list[dict] | None = None,
        style_profile: str = "",
    ) -> LLMJudgement:
        user = build_user_prompt(text, start, end, features, exemplars, style_profile)
        parsed = self._chat(SYSTEM_PROMPT, user, GRAMMAR)
        if not parsed:
            return HeuristicScorer().score(
                text, start, end, features, exemplars, style_profile
            ).model_copy(update={"provider": "llama-server-failed"})
        try:
            return LLMJudgement(
                score=int(max(0, min(100, int(parsed.get("score", 0))))),
                hook=str(parsed.get("hook", ""))[:90],
                title=str(parsed.get("title", ""))[:70],
                reason=str(parsed.get("reason", ""))[:200],
                understands_standalone=bool(parsed.get("understands_standalone", True)),
                has_payoff=bool(parsed.get("has_payoff", True)),
                provider=self.name,
            )
        except (TypeError, ValueError):
            return HeuristicScorer().score(
                text, start, end, features, exemplars, style_profile
            ).model_copy(update={"provider": "llama-server-invalid"})

    def critique(self, text: str) -> dict | None:
        parsed = self._chat(SYSTEM_PROMPT, build_critique_prompt(text), CRITIQUE_GRAMMAR)
        if not parsed:
            return None
        return {
            "standalone": bool(parsed.get("standalone", True)),
            "payoff": bool(parsed.get("payoff", True)),
            "verdict": str(parsed.get("verdict", "keep")),
            "note": str(parsed.get("note", ""))[:160],
        }


def resolve_scorer(llama_url: str = "") -> Scorer:
    if llama_url:
        scorer = LlamaServerScorer(llama_url)
        if scorer.available():
            return scorer
    return HeuristicScorer()


def probe_runner(base_url: str, timeout: float = 3.0) -> dict:
    """Check a llama-server address without scoring anything.

    Used by setup ("is the runner I was told about actually up?") and by the
    scoring row of the readiness check. Never raises: an unreachable runner is
    an ordinary answer, not an error, because the built-in scorer still works.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {"reachable": False, "models": [], "error": "No address set."}
    try:
        response = httpx.get(f"{base}/v1/models", timeout=timeout)
    except httpx.TimeoutException:
        return {
            "reachable": False,
            "models": [],
            "error": f"No answer within {timeout:.0f} seconds.",
        }
    except httpx.HTTPError:
        return {
            "reachable": False,
            "models": [],
            "error": "Nothing is listening at that address.",
        }
    if response.status_code != 200:
        return {
            "reachable": False,
            "models": [],
            "error": f"The address answered with status {response.status_code}.",
        }
    names: list[str] = []
    try:
        for item in response.json().get("data") or []:
            name = item.get("id")
            if name:
                names.append(str(name))
    except (AttributeError, TypeError, ValueError):
        pass
    return {"reachable": True, "models": names, "error": ""}
