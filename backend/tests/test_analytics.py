import json
import time

import pytest

from clipper import accounts, analytics, db
from clipper.publish import oauth
from clipper.publish.base import RemotePost


class FakeAdapter:
    def __init__(self, posts, profile=None):
        self.posts = posts
        self.profile = profile or {"followers": 1234}
        self.calls = []

    def fetch_posts(self, token, limit=50):
        self.calls.append((token, limit))
        return self.posts

    def fetch_profile(self, token):
        return self.profile


def connect():
    return accounts.connect_account(
        "youtube",
        oauth.TokenBundle(access_token="token", expires_at=time.time() + 3600),
        "client-id",
        "client-secret",
        identity={"external_id": "UC1", "display_name": "Channel"},
    )


def remote(index, views, likes=10, comments=1, shares=0, saves=0, age_h=48):
    return RemotePost(
        platform_post_id=f"vid{index}",
        url=f"https://youtu.be/vid{index}",
        published_at=time.time() - age_h * 3600,
        title=f"Clip {index}",
        caption=f"Clip {index} #shorts",
        duration_s=30,
        metrics={"views": views, "likes": likes, "comments": comments, "shares": shares, "saves": saves},
    )


def test_composite_rewards_reach_and_interaction():
    low = analytics.composite_score({"views": 100, "likes": 1}, duration_s=30, age_hours=48)
    high = analytics.composite_score({"views": 100_000, "likes": 1000, "comments": 100}, duration_s=30, age_hours=48)
    assert high > low
    assert 0 <= low <= 100 and 0 <= high <= 100
    assert analytics.composite_score({}, duration_s=30, age_hours=0) == 0.0


def test_sync_creates_posts_metrics_and_balanced_labels(clean_db):
    account = connect()
    posts = [remote(i, views=100 * (i + 1), likes=10 + i) for i in range(10)]
    summary = analytics.sync_account(account.id, adapter=FakeAdapter(posts), now=time.time())
    assert summary["new_posts"] == 10
    assert summary["labels"]["labeled"] == 10
    assert summary["labels"]["positives"] == 5
    assert summary["labels"]["negatives"] == 5
    assert summary["followers"] == 1234
    saved = analytics.list_posts(account.id)
    assert len(saved) == 10
    assert all(p["metrics"]["views"] > 0 for p in saved)
    assert all(p["label"] in (0, 1) for p in saved)
    assert accounts.get_account(account.id).last_sync_at > 0


def test_sync_is_idempotent_and_captures_a_new_metric_point(clean_db):
    account = connect()
    adapter = FakeAdapter([remote(1, 1000)])
    first = analytics.sync_account(account.id, adapter=adapter)
    second = analytics.sync_account(account.id, adapter=adapter)
    assert first["new_posts"] == 1
    assert second["new_posts"] == 0
    assert len(analytics.list_posts(account.id)) == 1
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM post_metrics").fetchone()["n"]
    assert count == 2


def test_sync_preserves_app_features_for_the_personal_model(clean_db):
    account = connect()
    analytics.sync_account(account.id, adapter=FakeAdapter([remote(1, 1000)]))
    post_id = analytics.list_posts(account.id)[0]["id"]
    features = {"hook_lexicon_hits": 3, "words_per_sec": 4.2}
    signals = {"audio": 0.7, "hook_lexicon": 0.8}
    llm = {"score": 81, "has_payoff": True}
    with db.connect() as conn:
        conn.execute(
            "UPDATE posts SET origin=?, feature_coverage=?, features=?, signals=?, llm=? WHERE id=?",
            ("app", "full", json.dumps(features), json.dumps(signals), json.dumps(llm), post_id),
        )
        conn.execute("UPDATE post_metrics SET label=1 WHERE post_id=?", (post_id,))
    rows = analytics.training_rows(account.id)
    assert len(rows) == 1
    assert rows[0]["features"] == features
    assert rows[0]["signals"] == signals
    assert rows[0]["llm"] == llm
    assert rows[0]["label"] == 1


def test_young_or_tiny_posts_are_not_labeled(clean_db):
    account = connect()
    analytics.sync_account(account.id, adapter=FakeAdapter([
        remote(1, 10, age_h=1),
        remote(2, 10_000, age_h=48),
    ]))
    posts = analytics.list_posts(account.id)
    assert {p["label"] for p in posts} == {None}


def test_baseline_explains_its_sample(clean_db):
    account = connect()
    analytics.sync_account(account.id, adapter=FakeAdapter([remote(i, 100 * (i + 1)) for i in range(10)]))
    base = analytics.baseline(account.id)
    assert base["eligible_posts"] == 10
    assert base["labels_ready"] is True
    assert base["median_composite"] > 0


def test_unsupported_platform_is_honest():
    with pytest.raises(Exception, match="not enabled"):
        analytics.adapter_for_analytics("tiktok")


def test_hashtags_are_extracted_without_duplicates():
    tags = analytics._hashtags("one #Shorts #shorts #clip")
    assert tags == ["#Shorts", "#shorts", "#clip"]

