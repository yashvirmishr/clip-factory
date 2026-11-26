from pathlib import Path

import httpx
import pytest

from clipper.publish.base import PublishError, UploadRequest
from clipper.publish.limits import MediaInfo
from clipper.publish.x import XAdapter


class FakeSession:
    def __init__(self, post_responses, get_responses=None):
        self.post_responses = list(post_responses)
        self.get_responses = list(get_responses or [])
        self.posts = []
        self.gets = []

    def post(self, url, data=None, files=None, json=None, headers=None):
        self.posts.append({"url": url, "data": data, "files": files, "json": json, "headers": headers})
        return self.post_responses.pop(0)

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append({"url": url, "params": params, "headers": headers})
        return self.get_responses.pop(0)

    def close(self):
        pass


def request(tmp_path):
    path = Path(tmp_path) / "clip.mp4"
    path.write_bytes(b"video-bytes")
    return UploadRequest(
        account_id="acct",
        media_path=str(path),
        title="A clip",
        description="Watch this",
        tags=["clip"],
        visibility="public",
        media=MediaInfo(duration=30, width=1080, height=1920, size_bytes=11, has_audio=True, format="mp4"),
    )


def test_upload_uses_init_append_finalize_and_tweet(tmp_path):
    session = FakeSession(
        [
            httpx.Response(200, json={"data": {"id": "media1"}}),
            httpx.Response(204),
            httpx.Response(200, json={"data": {"processing_info": {"state": "succeeded"}}}),
            httpx.Response(201, json={"data": {"id": "tweet1"}}),
        ],
        [httpx.Response(200, json={"data": {"processing_info": {"state": "succeeded"}}})],
    )
    adapter = XAdapter(session)
    result = adapter.upload(request(tmp_path), "token")
    assert result.platform_post_id == "tweet1"
    assert result.url == "https://x.com/i/status/tweet1"
    assert session.posts[0]["data"]["command"] == "INIT"
    assert session.posts[1]["data"]["command"] == "APPEND"
    assert session.posts[1]["data"]["segment_index"] == "0"
    assert session.posts[1]["files"]["media"][1] == b"video-bytes"
    assert session.posts[2]["data"]["command"] == "FINALIZE"
    tweet = session.posts[3]["json"]
    assert tweet["media"]["media_ids"] == ["media1"]
    assert tweet["text"] == "Watch this\n\n#clip"


def test_upload_errors_are_structured(tmp_path):
    session = FakeSession([httpx.Response(401, json={"title": "Unauthorized"})])
    with pytest.raises(PublishError) as excinfo:
        XAdapter(session).upload(request(tmp_path), "bad")
    assert excinfo.value.code == "unauthorized"
    assert "reconnect" in str(excinfo.value).lower()


def test_fetch_posts_returns_normalized_metrics():
    session = FakeSession([], [
        httpx.Response(200, json={"data": {"id": "u1"}}),
        httpx.Response(200, json={"data": [{
            "id": "t1", "text": "hello", "created_at": "2026-01-01T00:00:00.000Z",
            "public_metrics": {"impression_count": 1000, "like_count": 20, "reply_count": 3, "retweet_count": 2, "quote_count": 1, "bookmark_count": 4},
        }]}),
    ])
    posts = XAdapter(session).fetch_posts("token", limit=10)
    assert len(posts) == 1
    assert posts[0].platform_post_id == "t1"
    assert posts[0].metrics == {"views": 1000, "likes": 20, "comments": 3, "shares": 3, "saves": 4}


def test_fetch_profile_reads_public_metrics():
    session = FakeSession([], [httpx.Response(200, json={"data": {
        "id": "u1", "public_metrics": {"followers_count": 42, "following_count": 7, "tweet_count": 9},
    }})])
    assert XAdapter(session).fetch_profile("token") == {"followers": 42, "following": 7, "posts": 9, "avatar_url": ""}
