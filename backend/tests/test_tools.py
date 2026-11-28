"""The two external programs: pinned, verified, and installed where PATH sees them."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from clipper import tools
from clipper.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A tools folder of its own, so tests never touch the real one."""
    directory = tmp_path / "tools"
    directory.mkdir()
    monkeypatch.setenv("CLIPPER_TOOLS_DIR", str(directory))
    return directory


def zip_payload(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_manifest_pins_a_real_hash_and_an_https_home():
    for tool in tools.TOOLS.values():
        assert tool.url.startswith("https://")
        assert len(tool.sha256) == 64
        int(tool.sha256, 16)  # hex, not a placeholder
        assert tool.size > 0
        assert tool.provides
        assert all(name.endswith(".exe") for name in tool.provides)


def test_status_says_when_this_platform_cannot_install(sandbox, monkeypatch):
    monkeypatch.setattr(tools, "automatic_install_supported", lambda: False)
    payload = tools.status()
    assert payload["automatic"] is False
    assert payload["bin_dir"] == str(sandbox)
    assert {item["id"] for item in payload["tools"]} == {"ffmpeg", "whisper"}


def test_status_reads_the_tools_folder(sandbox):
    (sandbox / "whisper-cli.exe").write_bytes(b"binary")
    payload = tools.status()
    whisper = next(item for item in payload["tools"] if item["id"] == "whisper")
    assert whisper["installed"] is True
    assert whisper["path"].endswith("whisper-cli.exe")


def test_install_refuses_another_platform(sandbox, monkeypatch):
    monkeypatch.setattr(tools, "automatic_install_supported", lambda: False)
    with pytest.raises(RuntimeError, match="Windows"):
        tools.install("whisper")


def test_a_bad_hash_deletes_the_download(sandbox, monkeypatch):
    tool = dataclasses.replace(tools.TOOLS["whisper"], sha256="0" * 64)
    monkeypatch.setitem(tools.TOOLS, tool.id, tool)
    monkeypatch.setattr(tools, "automatic_install_supported", lambda: True)

    def fake_download(tool_, dest, progress):
        dest.write_bytes(b"this is not the archive that was pinned")
        progress(1.0, dest.stat().st_size, dest.stat().st_size)

    monkeypatch.setattr(tools, "_download", fake_download)
    with pytest.raises(RuntimeError, match="SHA-256"):
        tools.install("whisper")
    assert not (sandbox / ".whisper.download").exists()
    assert not (sandbox / "whisper-cli.exe").exists()


def test_extract_copies_only_the_programs_and_rejects_traversal(sandbox):
    archive = sandbox / "bundle.zip"
    archive.write_bytes(
        zip_payload(
            {
                "Release/whisper-cli.exe": b"cli",
                "Release/ggml.dll": b"dll",
                "Release/bench.exe": b"not wanted",
            }
        )
    )
    written = tools._extract(archive, tools.TOOLS["whisper"], sandbox)
    assert sorted(written) == ["ggml.dll", "whisper-cli.exe"]
    assert (sandbox / "whisper-cli.exe").read_bytes() == b"cli"
    assert (sandbox / "ggml.dll").exists()
    assert not (sandbox / "bench.exe").exists()

    slipping = sandbox / "slip.zip"
    slipping.write_bytes(zip_payload({"../evil.exe": b"no"}))
    with pytest.raises(RuntimeError, match="safe path"):
        tools._extract(slipping, tools.TOOLS["whisper"], sandbox)
    assert not (sandbox.parent / "evil.exe").exists()


def test_install_verifies_unpacks_and_reports_progress(sandbox, monkeypatch):
    payload = zip_payload(
        {
            "Release/hello.exe": b"exe",
            "Release/ggml.dll": b"dll",
            "Release/other.exe": b"skip",
        }
    )
    tool = dataclasses.replace(
        tools.TOOLS["whisper"],
        id="hello",
        label="hello",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        provides=("hello.exe",),
        patterns=("hello.exe", "*.dll"),
    )
    monkeypatch.setitem(tools.TOOLS, "hello", tool)
    monkeypatch.setattr(tools, "automatic_install_supported", lambda: True)

    def fake_download(tool_, dest, progress):
        dest.write_bytes(payload)
        progress(1.0, len(payload), len(payload))

    monkeypatch.setattr(tools, "_download", fake_download)
    stages: list[str] = []

    def progress(stage, pct, detail=""):
        stages.append(stage)

    result = tools.install("hello", progress=progress)
    assert stages[0] == "download"
    assert stages[-3:] == ["verify", "unpack", "done"]
    assert sorted(result["files"]) == ["ggml.dll", "hello.exe"]
    assert (sandbox / "hello.exe").read_bytes() == b"exe"
    assert not (sandbox / "other.exe").exists()
    assert result["status"]["tools"][-1]["installed"] is True


def test_tools_endpoint_lists_and_dispatches(client, monkeypatch):
    payload = client.get("/api/tools").json()
    assert payload["bin_dir"]
    assert isinstance(payload["automatic"], bool)
    assert {item["id"] for item in payload["tools"]} == {"ffmpeg", "whisper"}

    assert client.post("/api/tools/unknown/install").status_code == 404

    monkeypatch.setattr(tools, "install", lambda tool_id, progress=None: {"tool": tool_id})
    started = client.post("/api/tools/whisper/install").json()
    assert started["kind"] == "tool"
    assert started["lane"] == "io"
