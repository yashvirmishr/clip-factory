from pathlib import Path

import httpx
import pytest

from clipper.publish import youtube
from clipper.publish.base import PublishError, UploadRequest
from clipper.publish.limits import MediaInfo


class FakeSession:
    def __init__(self, init_response, upload_responses):
        self.init_response = init_response
        self.upload_responses = list(upload_responses)
        self.posts = []
        self.puts = []

    def post(self, url, params=None, headers=None, content=None):
        self.posts.append({"url": url, "params": params, "headers": headers, "content": content})
        return self.init_response

    def put(self, url, headers=None, content=None):
        self.puts.append({"url": url, "headers": headers, "content": content})
        return self.upload_responses.pop(0)

    def close(self):
        pass


def request(tmp_path, name="clip.mp4"):
    path = Path(tmp_path) / name
    if not path.exists():
        path.write_bytes(b"video-bytes")
    return UploadRequest(
        account_id="acct_1",
        media_path=str(path),
        title="A title",
        description="A description",
        tags=["one", "two"],
        visibility="public",
        media=MediaInfo(duration=30, width=1080, height=1920, size_bytes=path.stat().st_size, has_audio=True, format="mp4"),
    )


def test_upload_opens_a_resumable_session_and_sends_metadata(tmp_path):
    path = Path(tmp_path) / "clip.mp4"
    path.write_bytes(b"video-bytes")
    session = FakeSession(
        httpx.Response(200, headers={"location": "https://upload.example/session"}),
        [httpx.Response(200, json={"id": "vid123"})],
    )
    adapter = youtube.YouTubeAdapter(session)
    req = request(tmp_path)
    stages = []
    result = adapter.upload(req, "token", lambda stage, pct, detail="": stages.append((stage, pct)))
    assert result.platform_post_id == "vid123"
    assert result.url == "https://youtu.be/vid123"
    assert session.posts[0]["url"] == youtube.UPLOAD_URL
    assert session.posts[0]["params"]["uploadType"] == "resumable"
    assert session.posts[0]["headers"]["Authorization"] == "Bearer token"
    assert b"A title" in session.posts[0]["content"]
    assert session.puts[0]["url"] == "https://upload.example/session"
    assert session.puts[0]["headers"]["Content-Range"] == f"bytes 0-10/{len(b'video-bytes')}"
    assert stages[-1] == ("done", 1.0)


def test_a_308_response_resumes_from_the_reported_offset(tmp_path, monkeypatch):
    path = Path(tmp_path) / "clip.mp4"
    path.write_bytes(b"abcdefgh")
    monkeypatch.setattr(youtube, "CHUNK_SIZE", 4)
    session = FakeSession(
        httpx.Response(200, headers={"location": "https://upload.example/session"}),
        [
            httpx.Response(308, headers={"range": "bytes=0-3"}),
            httpx.Response(200, json={"id": "vid456"}),
        ],
    )
    adapter = youtube.YouTubeAdapter(session)
    result = adapter.upload(request(tmp_path), "token")
    assert result.platform_post_id == "vid456"
    assert session.puts[0]["headers"]["Content-Range"] == "bytes 0-3/8"
    assert session.puts[1]["headers"]["Content-Range"] == "bytes 4-7/8"


def test_missing_file_is_a_publish_error(tmp_path):
    adapter = youtube.YouTubeAdapter(FakeSession(httpx.Response(200), []))
    req = UploadRequest(account_id="a", media_path=str(Path(tmp_path) / "nope.mp4"))
    with pytest.raises(PublishError, match="not found"):
        adapter.upload(req, "token")


def test_unauthorized_upload_is_not_retried_automatically(tmp_path):
    path = Path(tmp_path) / "clip.mp4"
    path.write_bytes(b"x")
    session = FakeSession(
        httpx.Response(401, json={"error": {"message": "Invalid Credentials", "status": "UNAUTHENTICATED"}}),
        [],
    )
    adapter = youtube.YouTubeAdapter(session)
    with pytest.raises(PublishError) as excinfo:
        adapter.upload(request(tmp_path), "bad-token")
    assert excinfo.value.retryable is False
    assert "reconnect" in str(excinfo.value).lower()


def test_quota_error_is_named_for_the_ui(tmp_path):
    path = Path(tmp_path) / "clip.mp4"
    path.write_bytes(b"x")
    session = FakeSession(
        httpx.Response(403, json={"error": {"message": "The request cannot be completed because you have exceeded your quota.", "status": "quotaExceeded"}}),
        [],
    )
    adapter = youtube.YouTubeAdapter(session)
    with pytest.raises(PublishError) as excinfo:
        adapter.upload(request(tmp_path), "token")
    assert excinfo.value.code == "quota"
    assert excinfo.value.retryable is False


def test_duration_parser_handles_shorts_durations():
    assert youtube._iso_duration("PT45S") == 45
    assert youtube._iso_duration("PT1M30S") == 90
    assert youtube._iso_duration("PT1H2M3S") == 3723
    assert youtube._iso_duration("") == 0

