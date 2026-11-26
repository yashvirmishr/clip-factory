import time
from pathlib import Path

import pytest

from clipper import accounts, db, secrets
from clipper.publish import oauth, queue
from clipper.publish.base import PublishError, PublishResult


def connect():
    return accounts.connect_account(
        "youtube",
        oauth.TokenBundle(access_token="token", expires_at=time.time() + 3600),
        "client-id",
        "client-secret",
        identity={"external_id": "UC1", "display_name": "Channel"},
    )


def file(tmp_path, name="clip.mp4"):
    path = Path(tmp_path) / name
    path.write_bytes(b"video")
    return path


class FakeAdapter:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def upload(self, request, token, progress):
        self.calls.append((request, token))
        progress("upload", 0.5, "half")
        if self.error:
            raise self.error
        return PublishResult(platform_post_id="vid1", url="https://youtu.be/vid1")


def enqueue(tmp_path, account, key=""):
    return queue.enqueue(
        platform="youtube",
        account_id=account.id,
        media_path=file(tmp_path),
        metadata={
            "title": "A title",
            "description": "desc",
            "tags": ["one"],
            "media": {
                "duration": 30,
                "width": 1080,
                "height": 1920,
                "size_bytes": 5,
                "has_audio": True,
                "format": "mp4",
            },
        },
        clip_id="clip1",
        idempotency_key=key,
    )


def test_enqueue_is_durable_and_idempotent(clean_db, tmp_path):
    account = connect()
    first = enqueue(tmp_path, account, "same-key")
    second = enqueue(tmp_path, account, "same-key")
    assert first["id"] == second["id"]
    assert first["status"] == "queued"
    assert first["metadata"]["title"] == "A title"
    assert queue.get_job(first["id"])["media_path"].endswith("clip.mp4")


def test_claim_next_marks_running_and_increments_attempts(clean_db, tmp_path):
    account = connect()
    job = enqueue(tmp_path, account)
    claimed = queue.claim_next()
    assert claimed["id"] == job["id"]
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert queue.claim_next() is None


def test_claim_by_id_is_atomic_and_respects_backoff(clean_db, tmp_path):
    account = connect()
    job = enqueue(tmp_path, account)
    claimed = queue.claim(job["id"])
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert queue.claim(job["id"]) is None
    queue.mark_failure(job["id"], "temporary", code="503", retryable=True)
    assert queue.claim(job["id"]) is None
    later = queue.get_job(job["id"])["next_attempt_at"] + 1
    assert queue.claim(job["id"], now=later)["status"] == "running"


def test_recover_returns_an_interrupted_upload_to_the_queue(clean_db, tmp_path):
    account = connect()
    job = enqueue(tmp_path, account)
    queue.claim_next()
    assert queue.get_job(job["id"])["status"] == "running"
    pending = queue.recover()
    saved = queue.get_job(job["id"])
    assert pending == [job["id"]]
    assert saved["status"] == "retry"
    assert saved["stage"] == "resuming after restart"
    assert queue.claim_next()["id"] == job["id"]


def test_process_uploads_and_creates_a_post(clean_db, tmp_path, monkeypatch):
    account = connect()
    job = enqueue(tmp_path, account)
    queue.claim_next()
    adapter = FakeAdapter()
    monkeypatch.setattr(queue, "adapter_for", lambda platform: adapter)
    monkeypatch.setattr(accounts, "access_token", lambda account_id: "token")
    stages = []
    done = queue.process(job["id"], lambda stage, pct, detail="": stages.append(stage))
    assert done["status"] == "done"
    assert done["platform_post_id"] == "vid1"
    assert stages == ["upload"]
    with db.connect() as conn:
        post = conn.execute("SELECT * FROM posts WHERE platform_post_id=?", ("vid1",)).fetchone()
    assert post is not None
    assert post["title"] == "A title"
    assert post["account_id"] == account.id


def test_retryable_failure_schedules_a_retry(clean_db, tmp_path, monkeypatch):
    account = connect()
    job = enqueue(tmp_path, account)
    queue.claim_next()
    monkeypatch.setattr(queue, "adapter_for", lambda platform: FakeAdapter(PublishError("temporary", code="503", retryable=True)))
    monkeypatch.setattr(accounts, "access_token", lambda account_id: "token")
    with pytest.raises(PublishError):
        queue.process(job["id"])
    saved = queue.get_job(job["id"])
    assert saved["status"] == "retry"
    assert saved["error_code"] == "503"
    assert saved["next_attempt_at"] > time.time()


def test_non_retryable_failure_stops(clean_db, tmp_path, monkeypatch):
    account = connect()
    job = enqueue(tmp_path, account)
    queue.claim_next()
    monkeypatch.setattr(queue, "adapter_for", lambda platform: FakeAdapter(PublishError("bad token", code="401")))
    monkeypatch.setattr(accounts, "access_token", lambda account_id: "token")
    with pytest.raises(PublishError):
        queue.process(job["id"])
    assert queue.get_job(job["id"])["status"] == "error"


def test_retry_resets_attempts_and_cancel_is_explicit(clean_db, tmp_path):
    account = connect()
    job = enqueue(tmp_path, account)
    queue.claim_next()
    queue.mark_failure(job["id"], "nope", code="500", retryable=False)
    again = queue.retry(job["id"])
    assert again["status"] == "queued"
    assert again["attempts"] == 0
    cancelled = queue.cancel(job["id"])
    assert cancelled["status"] == "cancelled"


def test_missing_account_is_rejected_before_a_row_is_written(clean_db, tmp_path):
    account = connect()
    account_id = account.id
    accounts.delete_account(account_id)
    with pytest.raises(ValueError, match="not connected"):
        queue.enqueue(
            platform="youtube",
            account_id=account_id,
            media_path=file(tmp_path),
            metadata={},
        )


def test_mark_done_is_idempotent_for_the_same_platform_post(clean_db, tmp_path, monkeypatch):
    account = connect()
    job = enqueue(tmp_path, account)
    queue.claim_next()
    monkeypatch.setattr(queue, "adapter_for", lambda platform: FakeAdapter())
    monkeypatch.setattr(accounts, "access_token", lambda account_id: "token")
    queue.process(job["id"])
    queue.mark_done(job["id"], PublishResult(platform_post_id="vid1", url="https://youtu.be/vid1"))
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
    assert count == 1
    with pytest.raises(ValueError, match="already published"):
        queue.retry(job["id"])
