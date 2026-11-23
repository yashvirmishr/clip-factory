"""Learning loop facade.

Three layers, ordered by return on effort:

1. decision log      - captures labels + the exact feature vector at decision time
2. personal re-ranker- tiny logistic model, promoted only on held-out gain
3. few-shot memory   - retrieved exemplars + a derived style profile in the prompt

Fine-tuning is exported, never run in-app.
"""

from __future__ import annotations

import time

from .. import db
from ..config import SETTINGS, LearnConfig
from ..domain import ClipCandidate
from .features import COLUMNS, label_of, named_features
from .memory import exemplar_count, retrieve_exemplars, similarity_floor
from .profile import MIN_EDITS, summarize
from .ranker import (
    RankerModel,
    TrainOutcome,
    apply_ranker,
    quality_stats,
    train_from_decisions,
)

_RANKER_KEY = "ranker_model"
_RANKER_META_KEY = "ranker_meta"
_PROFILE_KEY = "style_profile"


class Learner:
    def __init__(self, cfg: LearnConfig | None = None) -> None:
        self.cfg = cfg or SETTINGS.learn
        self._model: RankerModel | None = None
        self._loaded_at = 0.0

    # ---- persisted artifacts ------------------------------------------
    def model(self) -> RankerModel | None:
        if self._model is None:
            self._model = RankerModel.from_dict(db.get_state(_RANKER_KEY, {}) or {})
        return self._model

    def reload(self) -> None:
        self._model = None

    def style_profile(self) -> str:
        payload = db.get_state(_PROFILE_KEY, {}) or {}
        return payload.get("profile", "") if isinstance(payload, dict) else ""

    def refresh_profile(self) -> dict:
        summary = summarize(db.list_hook_edits())
        db.set_state(_PROFILE_KEY, summary)
        return summary

    # ---- inference helpers --------------------------------------------
    def exemplars(self, text: str) -> list[dict]:
        if not text:
            return []
        rows = db.list_decisions(limit=400)
        picked = retrieve_exemplars(text, rows, self.cfg.few_shot_k)
        return similarity_floor(picked)

    def rerank(self, candidates: list[ClipCandidate]) -> None:
        apply_ranker(candidates, self.model())

    def is_active(self) -> bool:
        model = self.model()
        return bool(model and model.weights)

    # ---- feedback ------------------------------------------------------
    def record_decision(self, candidate: ClipCandidate, action: str, reason: str = "") -> TrainOutcome | None:
        db.record_decision(candidate, action, reason)
        if action in ("approve", "reject"):
            return self.maybe_retrain()
        return None

    def maybe_retrain(self) -> TrainOutcome:
        total = db.decision_count()
        meta = db.get_state(_RANKER_META_KEY, {}) or {}
        last_at = int(meta.get("trained_at_count", 0))
        if total < self.cfg.min_decisions_for_ranker:
            return TrainOutcome(
                promoted=False,
                reason=f"collecting feedback ({total}/{self.cfg.min_decisions_for_ranker})",
                n=total,
            )
        if total - last_at < self.cfg.retrain_every:
            return TrainOutcome(promoted=False, reason="waiting for more decisions", n=total)

        outcome = train_from_decisions(db.list_decisions(), self.cfg, self.model())
        db.set_state(
            _RANKER_META_KEY,
            {
                "trained_at_count": total,
                "last_attempt_at": time.time(),
                "promoted": outcome.promoted,
                "reason": outcome.reason,
                "auc": outcome.auc,
                "baseline_auc": outcome.baseline_auc,
            },
        )
        if outcome.promoted and outcome.model is not None:
            db.set_state(_RANKER_KEY, outcome.model.to_dict())
            db.set_state("ranker_history", self._history(outcome))
            self._model = outcome.model
        return outcome

    def _history(self, outcome: TrainOutcome) -> list[dict]:
        history = db.get_state("ranker_history", []) or []
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "at": time.time(),
                "auc": outcome.auc,
                "baseline_auc": outcome.baseline_auc,
                "n": outcome.n,
            }
        )
        return history[-40:]

    # ---- reporting -----------------------------------------------------
    def state(self) -> dict:
        decisions = db.list_decisions()
        model = self.model()
        profile = db.get_state(_PROFILE_KEY, {}) or {}
        edits = db.list_hook_edits()
        return {
            "decisions": len(decisions),
            "labels": exemplar_count(decisions),
            "learning_threshold": self.cfg.min_decisions_for_ranker,
            "progress_to_ranker": round(
                min(1.0, len(decisions) / max(1, self.cfg.min_decisions_for_ranker)), 3
            ),
            "ranker_active": bool(model and model.weights),
            "ranker_holdout_auc": (model.auc if model else None),
            "ranker_samples": (model.n if model else 0),
            "ranker_history": db.get_state("ranker_history", []) or [],
            "ranker_meta": db.get_state(_RANKER_META_KEY, {}) or {},
            "hook_edits": len(edits),
            "hook_edits_needed": max(0, MIN_EDITS - len(edits)),
            "style_profile": profile.get("profile", "") if isinstance(profile, dict) else "",
            "style_ready": bool(isinstance(profile, dict) and profile.get("ready")),
            "quality": quality_stats(decisions),
            "features": list(COLUMNS),
        }


LEARNER = Learner()
