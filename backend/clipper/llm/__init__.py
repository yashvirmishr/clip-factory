"""LLM scoring: GBNF-constrained judgement, with a deterministic stand-in."""

from .grammar import CRITIQUE_GRAMMAR, GRAMMAR
from .prompts import SYSTEM_PROMPT, build_critique_prompt, build_user_prompt
from .scorer import (
    HeuristicScorer,
    LlamaServerScorer,
    Scorer,
    resolve_scorer,
)

__all__ = [
    "CRITIQUE_GRAMMAR",
    "GRAMMAR",
    "SYSTEM_PROMPT",
    "HeuristicScorer",
    "LlamaServerScorer",
    "Scorer",
    "build_critique_prompt",
    "build_user_prompt",
    "resolve_scorer",
]
