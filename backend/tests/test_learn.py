import pytest

from clipper import db
from clipper.config import LearnConfig
from clipper.domain import ClipCandidate, LLMJudgement, WindowFeatures
from clipper.learn import Learner
from clipper.learn.features import COLUMNS, label_of
from clipper.learn.memory import retrieve_exemplars, similarity_floor
from clipper.learn.profile import summarize
from clipper.learn.ranker import (
    RankerModel,
    apply_ranker,
    auc_score,
    build_dataset,
    train_from_decisions,
)
import numpy as np


def decision_row(
    i: int, label: int, duration: float, final: float, text: str | None = None, score: int | None = None
) -> dict:
    judgement = LLMJudgement(
        score=score if score is not None else (92 if label else 12),
        hook=f"hook {i}", title="t", reason="r",
        understands_standalone=True, has_payoff=True,
    )
    return {
        "action": "approve" if label else "reject",
        "final": final,
        "llm_score": judgement.score,
        "llm": judgement.model_dump(),
        "features": WindowFeatures(
            duration=duration,
            word_count=60,
            words_per_sec=2.0,
            mean_word_prob=0.95,
            speech_coverage=0.9,
            start_in_stream=i * 10.0,
            end_in_stream=i * 10.0 + duration,
        ).model_dump(),
        "signals": {"audio": 0.5, "excitement": 0.5, "chat": 0.5, "speech": 0.5, "hook_lexicon": 0.5},
        "text": text or f"clip number {i} about the broken controller",
        "hook": f"hook {i}",
        "reason": "",
        "created_at": float(i),
    }


def test_auc_handles_ordering_and_missing_class():
    labels = np.array([0, 0, 1, 1], dtype=np.float32)
    assert auc_score(labels, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert auc_score(labels, np.array([0.9, 0.8, 0.2, 0.1])) == pytest.approx(0.0)
    assert auc_score(np.ones(4), np.array([0.1, 0.2, 0.8, 0.9])) == 0.5


def test_label_mapping():
    assert label_of("approve") == 1
    assert label_of("export") == 1
    assert label_of("reject") == 0
    assert label_of("view") is None


def test_dataset_shape_matches_columns():
    rows = [decision_row(i, i % 2, 30.0, 0.5) for i in range(6)]
    X, y, baseline = build_dataset(rows)
    assert X.shape == (6, len(COLUMNS))
    assert y.tolist() == [0, 1, 0, 1, 0, 1]
    assert baseline.shape == (6,)


def test_ranker_needs_enough_decisions():
    cfg = LearnConfig(min_decisions_for_ranker=40)
    outcome = train_from_decisions([decision_row(i, i % 2, 30.0, 0.5) for i in range(10)], cfg)
    assert outcome.promoted is False
    assert "more decisions" in outcome.reason


def test_ranker_is_promoted_when_it_beats_the_baseline_out_of_sample():
    rows = []
    for i in range(160):
        label = i % 2
        # Baseline final score is anti-correlated with the label; duration is
        # correlated. A working learner must find the correlated feature.
        rows.append(decision_row(i, label, 80.0 if label else 10.0, 0.15 if label else 0.9))
    cfg = LearnConfig(min_decisions_for_ranker=40, epochs=600, lr=0.1)
    outcome = train_from_decisions(rows, cfg)
    assert outcome.promoted is True, outcome.reason
    assert outcome.auc > 0.8
    assert outcome.baseline_auc < 0.5


def test_ranker_is_not_promoted_without_held_out_gain():
    # Identical features and identical model scores for both labels: there is
    # nothing to learn, so promotion must be refused rather than fitted noise.
    rows = [decision_row(i, i % 2, 30.0, 0.9, score=50) for i in range(120)]
    cfg = LearnConfig(min_decisions_for_ranker=40)
    outcome = train_from_decisions(rows, cfg)
    assert outcome.promoted is False


def test_ranker_model_round_trips_through_json():
    model = RankerModel(
        weights=[0.1] * len(COLUMNS), bias=0.2, mean=[0.0] * len(COLUMNS),
        std=[1.0] * len(COLUMNS), n=10, auc=0.7,
    )
    restored = RankerModel.from_dict(model.to_dict())
    assert restored is not None
    assert restored.auc == 0.7
    assert RankerModel.from_dict({"columns": ["nope"]}) is None


def test_apply_ranker_blends_rather_than_replaces():
    weights = [0.0] * len(COLUMNS)
    weights[COLUMNS.index("duration")] = 4.0
    model = RankerModel(
        weights=weights,
        bias=0.0,
        mean=[0.0] * len(COLUMNS),
        std=[1.0] * len(COLUMNS),
    )
    candidate = ClipCandidate(
        id="x", source_id="s", start=0.0, end=30.0, text="hello",
        fused=0.5, final=0.5,
        features=WindowFeatures(duration=90.0, word_count=200),
        signals={},
    )
    apply_ranker([candidate], model, weight=0.5)
    assert 0.5 < candidate.final <= 1.0


def test_learner_persists_promoted_ranker(clean_db):
    learner = Learner(LearnConfig(min_decisions_for_ranker=40, epochs=600, lr=0.1))
    for i in range(160):
        label = i % 2
        candidate = ClipCandidate(
            id=f"c{i}", source_id="s", start=i * 10.0, end=i * 10.0 + (80 if label else 10),
            text=f"clip number {i}",
            fused=0.15 if label else 0.9,
            final=0.15 if label else 0.9,
            llm=LLMJudgement(score=92 if label else 12, hook="h", provider="test"),
            features=WindowFeatures(
                duration=80.0 if label else 10.0, word_count=60, words_per_sec=2.0,
                mean_word_prob=0.95, speech_coverage=0.9,
                start_in_stream=i * 10.0, end_in_stream=i * 10.0 + 30,
            ),
            signals={"audio": 0.5, "excitement": 0.5, "chat": 0.5, "speech": 0.5, "hook_lexicon": 0.5},
        )
        db.record_decision(candidate, "approve" if label else "reject")

    outcome = learner.maybe_retrain()
    assert outcome.promoted is True
    learner.reload()
    assert learner.is_active()
    assert learner.state()["ranker_active"] is True


def test_progress_towards_ranker_is_reported(clean_db):
    learner = Learner(LearnConfig(min_decisions_for_ranker=40))
    candidate = ClipCandidate(id="c", source_id="s", start=0, end=30, text="hello")
    learner.record_decision(candidate, "approve")
    state = learner.state()
    assert state["decisions"] == 1
    assert state["ranker_active"] is False
    assert 0 < state["progress_to_ranker"] < 1


# ------------------------------------------------------------------ profile
def test_style_profile_learns_shortening():
    edits = [
        {"before": "this is a really long hook that goes on and on forever", "after": "short hook"},
        {"before": "another extremely wordy hook about the same old thing", "after": "punchy line"},
        {"before": "yet another overly long and rambling hook here", "after": "tight hook"},
        {"before": "one more verbose hook that nobody would ever read", "after": "quick hook"},
        {"before": "a long winded hook with lots of extra words in it", "after": "snappy"},
        {"before": "the final very long hook in this test fixture list", "after": "clean hook"},
    ]
    summary = summarize(edits)
    assert summary["ready"] is True
    assert "Shortens hooks" in summary["profile"]


def test_style_profile_stays_empty_below_threshold():
    summary = summarize([{"before": "a b c d e f", "after": "a b"}])
    assert summary["ready"] is False
    assert summary["profile"] == ""


# ------------------------------------------------------------------- memory
def test_exemplar_retrieval_prefers_similar_and_keeps_both_classes():
    rows = [
        decision_row(1, 1, 30.0, 0.9, "the controller exploded and nobody expected it"),
        decision_row(2, 0, 30.0, 0.9, "sponsorship rates are up this quarter across the board"),
        decision_row(3, 1, 30.0, 0.9, "controller exploded live on stream and chat lost it"),
        decision_row(4, 0, 30.0, 0.9, "unrelated discussion about quarterly sponsorship rates"),
    ]
    picked = retrieve_exemplars("my controller exploded on stream", rows, k=1)
    assert len(picked) == 2
    assert picked[0]["action"] in {"approve", "reject"}
    assert any(p["action"] == "reject" for p in picked)
    assert all(p["similarity"] >= 0.0 for p in picked)


def test_similarity_floor_drops_unrelated_exemplars():
    picked = [{"similarity": 0.9}, {"similarity": 0.01}]
    assert len(similarity_floor(picked, floor=0.15)) == 1
