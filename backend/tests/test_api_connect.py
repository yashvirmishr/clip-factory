import time

import pytest
from fastapi.testclient import TestClient

from clipper import accounts, analytics, api
from clipper.publish import oauth
from clipper.publish.base import RemotePost


class FakeAdapter:
    def fetch_posts(self, token, limit=50):
        now = time.time()
        return [
            RemotePost(
                platform_post_id=f"v{i}", url=f"https://youtu.be/v{i}",
                published_at=now - 48 * 3600, title=f"Clip {i}", duration_s=30,
                metrics={"views": 100 * (i + 1), "likes": 10 + i, "comments": 1},
            )
            for i in range(8)
        ]

    def fetch_profile(self, token):
        return {"followers": 42}


def connect(platform="youtube"):
    return accounts.connect_account(
        platform,
        oauth.TokenBundle(access_token="token", expires_at=time.time() + 3600),
        "client-id", "client-secret",
        identity={"external_id": f"ext-{platform}", "display_name": platform.title()},
    )


def test_accounts_and_learning_routes_are_local_and_honest(clean_db):
    with TestClient(api.app) as client:
        listing = client.get("/api/accounts")
        assert listing.status_code == 200
        assert {row["platform"] for row in listing.json()["platforms"]} >= {"youtube", "x"}
        personal = client.get("/api/learn/personal")
        assert personal.status_code == 200
        assert personal.json()["blend_cap"] == 0.2
        weekly = client.get("/api/learning/weekly")
        assert weekly.status_code == 200
        assert weekly.json()["interval_days"] == 7


def test_account_sync_posts_and_overview(clean_db, monkeypatch):
    account = connect()
    monkeypatch.setattr(analytics, "adapter_for_analytics", lambda platform: FakeAdapter())
    with TestClient(api.app) as client:
        synced = client.post(f"/api/accounts/{account.id}/sync")
        assert synced.status_code == 200, synced.text
        assert synced.json()["new_posts"] == 8
        posts = client.get(f"/api/accounts/{account.id}/posts")
        assert posts.status_code == 200
        assert len(posts.json()["posts"]) == 8
        overview = client.get(f"/api/accounts/{account.id}/overview")
        assert overview.status_code == 200
        assert overview.json()["baseline"]["eligible_posts"] == 8
        all_posts = client.get("/api/posts")
        assert all_posts.status_code == 200
        assert len(all_posts.json()["posts"]) == 8


def test_weekly_run_syncs_accounts_and_schedules_the_next_run(clean_db, monkeypatch):
    connect()
    monkeypatch.setattr(analytics, "adapter_for_analytics", lambda platform: FakeAdapter())
    with TestClient(api.app) as client:
        ran = client.post("/api/learning/weekly/run")
        assert ran.status_code == 200, ran.text
        body = ran.json()
        assert body["last_run"] > 0
        assert body["next_run"] > body["last_run"]
        assert body["results"][0]["ok"] is True
        state = client.get("/api/learning/weekly").json()
        assert state["due"] is False


def test_publish_create_accepts_x_and_stores_a_job(clean_db, monkeypatch, tmp_path):
    account = connect("x")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not really a video")
    monkeypatch.setattr(api, "_submit_publish", lambda job_id: None)
    with TestClient(api.app) as client:
        response = client.post("/api/publish", json={
            "platform": "x",
            "account_id": account.id,
            "media_path": str(media),
            "media": {"duration": 30, "width": 1080, "height": 1920, "size_bytes": 18, "has_audio": True, "format": "mp4"},
            "caption": "A test clip",
            "visibility": "public",
            "metadata": {"title": "Overridden", "visibility": "private"},
        })
        assert response.status_code == 200, response.text
        job = response.json()
        assert job["platform"] == "x"
        assert job["status"] == "queued"
        assert job["metadata"]["visibility"] == "public"
        assert job["metadata"]["title"] == ""
        assert job["metadata"]["feature_coverage"] == "none"
        listed = client.get("/api/publish/jobs")
        assert listed.json()["jobs"][0]["id"] == job["id"]


def test_scheduled_publish_waits_for_its_time(clean_db, monkeypatch, tmp_path):
    account = connect("x")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not really a video")
    submitted = []
    monkeypatch.setattr(api, "_submit_publish", lambda job_id: submitted.append(job_id))
    when = time.time() + 3600
    with TestClient(api.app) as client:
        response = client.post("/api/publish", json={
            "platform": "x",
            "account_id": account.id,
            "media_path": str(media),
            "media": {"duration": 30, "width": 1080, "height": 1920, "size_bytes": 18, "has_audio": True, "format": "mp4"},
            "caption": "Later clip",
            "visibility": "public",
            "scheduled_at": when,
        })
        assert response.status_code == 200, response.text
        job = response.json()
        assert submitted == []
        assert job["scheduled_at"] == pytest.approx(when, abs=1)
        assert job["next_attempt_at"] == pytest.approx(when, abs=1)
        assert api.publish_queue.next_pending() is None
        assert api.publish_queue.next_pending(now=when + 1)["id"] == job["id"]


def test_publish_rejects_a_time_in_the_past(clean_db, tmp_path):
    account = connect("x")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    with TestClient(api.app) as client:
        response = client.post("/api/publish", json={
            "platform": "x",
            "account_id": account.id,
            "media_path": str(media),
            "media": {"duration": 30, "width": 1080, "height": 1920, "size_bytes": 1, "has_audio": True, "format": "mp4"},
            "caption": "Too late",
            "visibility": "public",
            "scheduled_at": time.time() - 3600,
        })
        assert response.status_code == 400
        assert "future" in response.json()["detail"].lower()


def test_publish_snapshots_the_clip_features_for_the_personal_model(clean_db, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from clipper.domain import WindowFeatures

    account = connect("x")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not really a video")
    candidate = SimpleNamespace(
        features=WindowFeatures(duration=30, word_count=80),
        signals={"audio": 0.7},
        llm=SimpleNamespace(model_dump=lambda: {"score": 81}),
    )
    monkeypatch.setattr(api.db, "find_candidate", lambda *_: candidate)
    monkeypatch.setattr(api, "_submit_publish", lambda job_id: None)
    with TestClient(api.app) as client:
        response = client.post("/api/publish", json={
            "platform": "x",
            "account_id": account.id,
            "media_path": str(media),
            "media": {"duration": 30, "width": 1080, "height": 1920, "size_bytes": 18, "has_audio": True, "format": "mp4"},
            "caption": "A test clip",
            "visibility": "public",
            "source_id": "src1",
            "clip_id": "clip1",
        })
        assert response.status_code == 200, response.text
        metadata = response.json()["metadata"]
        assert metadata["feature_coverage"] == "full"
        assert metadata["features"]["duration"] == 30
        assert metadata["signals"] == {"audio": 0.7}
        assert metadata["llm"]["score"] == 81


def test_publish_rejects_a_mismatched_account(clean_db, tmp_path):
    account = connect("youtube")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    with TestClient(api.app) as client:
        response = client.post("/api/publish", json={
            "platform": "x",
            "account_id": account.id,
            "media_path": str(media),
            "media": {"duration": 30, "width": 1080, "height": 1920, "size_bytes": 1, "has_audio": True, "format": "mp4"},
            "caption": "A test clip",
            "visibility": "public",
        })
        assert response.status_code == 400
