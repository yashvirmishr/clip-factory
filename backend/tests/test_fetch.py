"""URL import: detection, the no-yt-dlp path, and the download contract.

Nothing here touches the network. The download itself is exercised through a fake
yt-dlp module, because a test that depends on YouTube being reachable and
unbothered is a test that fails for reasons unrelated to this code.
"""

import sys
import types

import pytest

from clipper.pipeline import fetch


def test_url_detection():
    assert fetch.is_url("https://www.twitch.tv/videos/123")
    assert fetch.is_url("http://example.com/a.mp4")
    assert not fetch.is_url("C:/VODs/stream.mp4")
    assert not fetch.is_url("/home/me/stream.mp4")
    assert not fetch.is_url("")
    assert not fetch.is_url("https://")


def test_available_reports_a_version_when_installed():
    version = fetch.available()
    # Empty when yt-dlp is missing; the app degrades rather than crashing.
    assert version == "" or version[0].isdigit()


def test_missing_yt_dlp_explains_what_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "available", lambda: "")
    with pytest.raises(fetch.FetchError) as error:
        fetch.fetch("https://example.com/v", tmp_path)
    assert "pip install yt-dlp" in str(error.value)


def test_clean_drops_the_error_prefix_and_newlines():
    cleaned = fetch._clean("ERROR: [youtube] abc: Video unavailable\nSome detail")
    assert not cleaned.startswith("ERROR")
    assert "\n" not in cleaned


def _fake_ytdlp(tmp_path, size=20_000, fail: str | None = None, title="A stream"):
    """Minimal stand-in for yt_dlp.YoutubeDL with the surface fetch() uses."""

    class FakeYDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            for hook in self.options["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": size // 2, "total_bytes": size})
                hook({"status": "finished"})
            if fail:
                raise _FakeDownloadError(fail)
            target = tmp_path / "abc123.mp4"
            target.write_bytes(b"\0" * size)
            return {
                "id": "abc123",
                "title": title,
                "duration": 120.0,
                "requested_downloads": [{"filepath": str(target)}],
            }

    class _FakeDownloadError(Exception):
        pass

    module = types.SimpleNamespace(
        YoutubeDL=FakeYDL,
        version=types.SimpleNamespace(__version__="9999.1.1"),
        utils=types.SimpleNamespace(DownloadError=_FakeDownloadError),
    )
    return module


def test_fetch_reports_progress_and_returns_the_file(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", _fake_ytdlp(tmp_path))
    monkeypatch.setattr(fetch, "available", lambda: "9999.1.1")

    seen = []
    result = fetch.fetch(
        "https://example.com/v", tmp_path, progress=lambda pct, detail: seen.append((pct, detail))
    )

    assert result.path.exists()
    assert result.title == "A stream"
    assert result.duration == 120.0
    assert seen and seen[-1][0] >= 0.5
    # The format is pinned so the handoff target can decode it.
    assert result.path.suffix == ".mp4"


def test_fetch_turns_a_download_error_into_a_readable_message(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", _fake_ytdlp(tmp_path, fail="ERROR: Video unavailable"))
    monkeypatch.setattr(fetch, "available", lambda: "9999.1.1")

    with pytest.raises(fetch.FetchError) as error:
        fetch.fetch("https://example.com/v", tmp_path)
    assert "Video unavailable" in str(error.value)


def test_fetch_uses_a_single_item_from_a_playlist(tmp_path, monkeypatch):
    module = _fake_ytdlp(tmp_path)
    inner = module.YoutubeDL.extract_info

    class PlaylistYDL(module.YoutubeDL):
        def extract_info(self, url, download=True):
            item = inner(self, url, download)
            return {"_type": "playlist", "entries": [item]}

    module.YoutubeDL = PlaylistYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    monkeypatch.setattr(fetch, "available", lambda: "9999.1.1")

    result = fetch.fetch("https://example.com/playlist", tmp_path)
    assert result.video_id == "abc123"


def test_a_url_with_no_file_on_disk_is_an_error(tmp_path, monkeypatch):
    module = _fake_ytdlp(tmp_path)
    inner = module.YoutubeDL.extract_info

    class NoFileYDL(module.YoutubeDL):
        def extract_info(self, url, download=True):
            inner(self, url, download)
            (tmp_path / "abc123.mp4").unlink()
            return {"id": "abc123", "title": "x", "duration": 1.0}

    module.YoutubeDL = NoFileYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    monkeypatch.setattr(fetch, "available", lambda: "9999.1.1")

    with pytest.raises(fetch.FetchError):
        fetch.fetch("https://example.com/v", tmp_path)
