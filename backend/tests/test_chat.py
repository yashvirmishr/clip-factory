"""Chat replay: URL parsing, paged fetch, artifact round-trip.

No network here. The GraphQL walk is driven by a fake client that pages like
Twitch does, so paging, offset collection, coverage and the failure messages are
all pinned without depending on a VOD that still exists.
"""

import json

import pytest

from clipper import service
from clipper.domain import SourceInfo
from clipper.pipeline import chat


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeClient:
    """Pages of comments by offset; records the offsets it was asked for."""

    def __init__(self, pages, length=600.0, status=200, errors=None):
        self.pages = pages
        self.length = length
        self.status = status
        self.errors = errors
        self.starts = []

    def post(self, url, json=None, headers=None):
        self.starts.append((json or {}).get("variables", {}).get("offset"))
        if self.errors:
            return FakeResponse({"errors": self.errors})
        index = len(self.starts) - 1
        page = self.pages[index] if index < len(self.pages) else []
        edges = [{"node": {"contentOffsetSeconds": offset}} for offset in page]
        body = {
            "data": {
                "video": {
                    "lengthSeconds": self.length,
                    "comments": {
                        "edges": edges,
                        "pageInfo": {"hasNextPage": index + 1 < len(self.pages)},
                    },
                }
            }
        }
        return FakeResponse(body, self.status)

    def close(self):
        pass


def test_vod_id_from_every_shape():
    assert chat.vod_id("https://www.twitch.tv/videos/1234567890") == "1234567890"
    assert chat.vod_id("twitch.tv/videos/42?t=1h2m") == "42"
    assert chat.vod_id("1234567890") == "1234567890"
    assert chat.vod_id("https://www.youtube.com/watch?v=abc") == ""
    assert chat.vod_id("") == ""
    assert not chat.is_twitch_vod("https://twitch.tv/somechannel")


def test_fetch_offsets_pages_through_the_whole_replay():
    client = FakeClient([[10.0, 20.0], [30.0], [40.0, 50.0]], length=100.0)
    offsets, length = chat.fetch_offsets("1", client=client)

    assert offsets == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert length == 100.0
    # Asked from the start, then from just past the last offset seen. The empty
    # page after the end is what stops the walk.
    assert client.starts == [0, 21, 31, 51]


def test_progress_is_reported_against_the_vod_length():
    seen = []
    client = FakeClient([[10.0, 20.0], [90.0]], length=100.0)
    chat.fetch_offsets("1", client=client, progress=lambda f, d: seen.append((f, d)))
    assert seen and 0 < seen[0][0] < 1
    assert seen[-1][0] > seen[0][0]
    assert "messages" in seen[-1][1]


def test_offsets_come_back_sorted():
    client = FakeClient([[30.0, 10.0], [50.0]], length=100.0)
    offsets, _ = chat.fetch_offsets("1", client=client)
    assert offsets == [10.0, 30.0, 50.0]


def test_overlapping_pages_are_not_counted_twice():
    # Twitch answers an offset seek with a window that starts before it, so a
    # page can repeat most of the previous one.
    client = FakeClient([[10.0, 10.0, 20.0], [18.0, 20.0, 20.0, 30.0]], length=100.0)
    offsets, _ = chat.fetch_offsets("1", client=client)
    # The burst at 10 is two messages, not one; the overlap at 20 is not four.
    assert offsets == [10.0, 10.0, 20.0, 30.0]
    assert client.starts[:2] == [0, 21]


def test_a_vod_with_no_chat_raises_a_specific_message(tmp_path):
    client = FakeClient([[]], length=100.0)
    with pytest.raises(chat.ChatError) as error:
        chat.fetch("https://twitch.tv/videos/1", tmp_path / "chat.json", client=client)
    assert "no chat replay" in str(error.value)


def test_http_errors_quote_the_status():
    client = FakeClient([[1.0]], status=429)
    with pytest.raises(chat.ChatError) as error:
        chat.fetch_offsets("1", client=client)
    assert "429" in str(error.value)


def test_graphql_errors_surface_the_message():
    client = FakeClient([[1.0]], errors=[{"message": "service timeout"}])
    with pytest.raises(chat.ChatError) as error:
        chat.fetch_offsets("1", client=client)
    assert "service timeout" in str(error.value)


def test_a_missing_video_says_so_instead_of_raising_keyerror():
    class NoVideo(FakeClient):
        def post(self, url, json=None, headers=None):
            return FakeResponse({"data": {"video": None}})

    with pytest.raises(chat.ChatError) as error:
        chat.fetch_offsets("1", client=NoVideo([[]]))
    assert "no video" in str(error.value)


def test_dump_round_trips_and_matches_the_existing_parser(tmp_path):
    path = chat.write_dump(tmp_path / "chat.json", [1.5, 60.0, 61.25])
    payload = json.loads(path.read_text())
    assert payload[0]["content_offset_seconds"] == 1.5
    assert chat.read_dump(path) == [1.5, 60.0, 61.25]


def test_a_junk_dump_reads_as_empty_rather_than_crashing(tmp_path):
    path = tmp_path / "chat.json"
    path.write_text("not json")
    assert chat.read_dump(path) == []
    path.write_text('{"content_offset_seconds": 1}')
    assert chat.read_dump(path) == []
    path.write_text('[{"content_offset_seconds": "soon"}]')
    assert chat.read_dump(path) == []
    assert chat.read_dump(tmp_path / "absent.json") == []


def test_coverage_reports_the_span_not_the_message_count():
    # 120 messages crammed into 10 s of a 600 s VOD is 2% coverage, not "lots".
    offsets = [300.0 + i * 0.08 for i in range(120)]
    info = chat.coverage(offsets, 600.0)
    assert info["messages"] == 120
    assert info["coverage"] < 0.03
    assert chat.coverage([], 600.0)["coverage"] == 0.0


def test_fetch_writes_the_artifact_and_reports_coverage(tmp_path):
    client = FakeClient([[10.0, 20.0], [300.0]], length=600.0)
    info = chat.fetch("https://twitch.tv/videos/99", tmp_path / "chat.json", client=client)

    assert (tmp_path / "chat.json").exists()
    assert info["vod_id"] == "99"
    assert info["messages"] == 3
    assert info["coverage"] > 0.4


def test_a_non_twitch_url_is_rejected_before_any_request(tmp_path):
    with pytest.raises(chat.ChatError) as error:
        chat.fetch("https://youtube.com/watch?v=abc", tmp_path / "chat.json")
    assert "Twitch VOD" in str(error.value)


def test_chat_status_names_the_vod_behind_a_url_source():
    source = SourceInfo(
        id="chat-url-source",
        name="vod",
        path="x.mp4",
        duration=600.0,
        origin_url="https://www.twitch.tv/videos/1234",
    )
    status = service.chat_status(source)
    assert status["twitch_vod"] == "1234"
    assert status["available"] is False


def test_fetch_chat_refuses_a_source_with_no_twitch_url():
    source = SourceInfo(id="chat-local-source", name="local", path="x.mp4", duration=10.0)
    with pytest.raises(chat.ChatError):
        service.fetch_chat(source)


def test_fetch_chat_writes_the_artifact_and_reports_it_available(monkeypatch):
    source = SourceInfo(
        id="chat-fetch-source",
        name="vod",
        path="x.mp4",
        duration=100.0,
        origin_url="https://twitch.tv/videos/5",
    )
    calls = {}

    def fake_fetch(url, target, progress=None, client=None, max_comments=0):
        calls["url"] = url
        calls["target"] = target
        calls["max_comments"] = max_comments
        chat.write_dump(target, [1.0, 2.0])
        return chat.coverage([1.0, 2.0], 100.0)

    monkeypatch.setattr(chat, "fetch", fake_fetch)
    info = service.fetch_chat(source)

    assert calls["url"] == source.origin_url
    assert calls["max_comments"] == chat.MAX_COMMENTS
    assert info["available"] is True
    assert service.chat_status(source)["messages"] == 2


def test_analyze_picks_up_a_dropped_in_chat_artifact():
    """A dump placed next to the transcript is used without being asked for."""
    source = SourceInfo(id="chat-artifact-source", name="local", path="x.mp4", duration=600.0)
    assert service.chat_path_for(source) is None

    target = service.artifacts_for(source.id) / service.CHAT_FILE
    chat.write_dump(target, [10.0, 300.0, 600.0])
    assert service.chat_path_for(source) == target

    status = service.chat_status(source)
    assert status["available"] is True
    assert status["messages"] == 3
    assert status["coverage"] == pytest.approx(0.983, abs=0.001)
