import json
import time

import numpy as np
import pytest

from clipper import accounts, db, personal
from clipper.domain import ClipCandidate, WindowFeatures
from clipper.learn.features import COLUMNS
from clipper.learn.ranker import RankerModel
from clipper.publish import oauth


def connect():
    return accounts.connect_account(
        "youtube",
        oauth.TokenBundle(access_token="token", expires_at=time.time() + 3600),
        "client-id",
        "client-secret",
        identity={"external_id": "UC1", "display_name": "Channel"},
    )


def seed(account_id, n=60):
    now = time.time()
    with db.connect() as conn:
        for i in range(n):
            post_id = f"post_{i}"
            label = 1 if i % 2 == 0 else 0
            features = {
                "duration": 30.0,
                "word_count": 80,
                "words_per_sec": 3.2,
                "hook_lexicon_hits": 5 if label else 0,
                "question_count": 1 if label else 0,
                "second_person": 1 if label else 0,
                "speech_coverage": 0.95,
                "mean_word_prob": 0.9,
            }
            conn.execute(
                """
                INSERT INTO posts (id, account_id, platform_post_id, url, published_at, title,
                    caption, hashtags, duration_s, clip_id, source_id, origin, status,
                    features, feature_coverage, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (post_id, account_id, f"v{i}", f"https://youtu.be/v{i}",
                 now - (n - i) * 3600, f"Clip {i}", "", "[]", 30.0,
                 f"clip{i}", "src1", "app", "published", json.dumps(features), "full", now, now),
            )
            conn.execute(
                """
                INSERT INTO post_metrics (post_id, captured_at, age_hours, views, likes,
                    comments, shares, saves, composite, label)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (post_id, now, 48.0, 1000 + i * 13, 10 + (i % 7), 1, 0, 0, 50.0, label),
            )


def test_training_waits_for_enough_settled_posts(clean_db):
    account = connect()
    seed(account.id, n=5)
    result = personal.train(account.id)
    assert result["promoted"] is False
    assert "more settled" in result["reason"]
    assert personal.active() is None


def test_a_real_signal_is_promoted_and_activated(clean_db):
    account = connect()
    seed(account.id, n=60)
    result = personal.train(account.id)
    assert result["n"] == 60
    assert result["positives"] == 30 and result["negatives"] == 30
    assert result["promoted"] is True, result
    assert result["auc"] > result["baseline_auc"]
    assert result["p_value"] < 0.05
    model = personal.active()
    assert model is not None and model.weights
    assert model.auc == result["auc"]
    assert personal.history()[0]["active"] is True


def test_activation_and_rollback_are_explicit(clean_db):
    account = connect()
    seed(account.id, n=60)
    result = personal.train(account.id)
    assert personal.activate(result["version"])["active"] is True
    personal.rollback()
    assert personal.active() is None
    assert personal.history()[0]["version"] == result["version"]


def test_a_model_that_missed_the_gate_cannot_be_activated(clean_db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO personal_models (version, created_at, payload, metrics, active, data_window) VALUES (?,?,?,?,0,?)",
            ("pm_weak", time.time(), "{}", json.dumps({"gain": 0.0, "p_value": 0.5}), "all"),
        )
    with pytest.raises(ValueError, match="promotion gate"):
        personal.activate("pm_weak")


def test_state_reports_the_learning_gate(clean_db):
    account = connect()
    seed(account.id, n=30)
    state = personal.state(account.id)
    assert state["posts"] == 30
    assert state["positives"] == 15
    assert state["ready"] is True
    assert state["blend_cap"] == 0.20


def test_blend_applies_both_learners_to_the_same_base_score():
    features = WindowFeatures(duration=30, word_count=80)
    candidate = ClipCandidate(
        id="c1", source_id="s1", start=0, end=30, text="hello",
        features=features, signals={"audio": 1.0}, final=0.4,
    )
    personal_model = RankerModel(
        weights=[1.0] + [0.0] * (len(COLUMNS) - 1),
        bias=0.0, mean=[0.0] * len(COLUMNS), std=[1.0] * len(COLUMNS),
        n=60, auc=0.9,
    )
    taste_model = RankerModel(
        weights=[0.0] * len(COLUMNS),
        bias=0.0, mean=[0.0] * len(COLUMNS), std=[1.0] * len(COLUMNS),
        n=40, auc=0.7,
    )
    personal.apply_blend([candidate], personal_model, taste_model, 0.20, 0.35)
    import numpy as np
    p = float(personal_model.predict_matrix(np.array([[1.0] + [0.0] * (len(COLUMNS) - 1)]))[0])
    t = 0.5
    assert candidate.final == pytest.approx(0.4 * 0.45 + p * 0.20 + t * 0.35, abs=1e-4)


def test_blend_scales_down_when_the_cap_would_be_exceeded():
    candidate = ClipCandidate(
        id="c1", source_id="s1", start=0, end=30, text="hello",
        features=WindowFeatures(), final=0.4,
    )
    model = RankerModel(
        weights=[1.0] + [0.0] * (len(COLUMNS) - 1),
        bias=0.0, mean=[0.0] * len(COLUMNS), std=[1.0] * len(COLUMNS),
    )
    taste = RankerModel(
        weights=[0.0] * len(COLUMNS),
        bias=0.0, mean=[0.0] * len(COLUMNS), std=[1.0] * len(COLUMNS),
    )
    personal.apply_blend([candidate], model, taste, 0.4, 0.4)
    # 0.8 of weight is scaled to 0.55; the base keeps 0.45.
    p = 0.5
    assert candidate.final == pytest.approx(0.4 * 0.45 + p * 0.55, abs=1e-4)
