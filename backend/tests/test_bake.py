"""Baking the reel: one folder, no stale files, and a failure that is recorded.

The renderer itself is exercised elsewhere; here it is replaced so the folder
bookkeeping - which is what a bake adds - is tested without decoding video.
"""

import json
from pathlib import Path

import pytest

from clipper.config import SETTINGS
from clipper.domain import AnalysisResult, ClipCandidate, SourceInfo
from clipper.editors import bake


class Candidate(ClipCandidate):
    pass


@pytest.fixture
def source() -> SourceInfo:
    return SourceInfo(id="bakesrc", name="Bake source", path="C:/media/x.mp4", duration=120.0, width=1920, height=1080)


def _analysis(source: SourceInfo, ids: list[str]) -> AnalysisResult:
    return AnalysisResult(
        source=source,
        asr_backend="stub",
        llm_backend="stub",
        candidates=[
            ClipCandidate(id=clip_id, source_id=source.id, start=index * 10.0, end=index * 10.0 + 8.0, text="hi there", rank=index + 1)
            for index, clip_id in enumerate(ids)
        ],
    )


@pytest.fixture
def fake_render(monkeypatch):
    """A render that writes a small file, or fails for ``fail_id``."""
    calls: list[str] = []
    state = {"fail": ""}

    def render_clip(source, candidate, preset_key="hormozi", framing="blur", force=False, progress=None):
        calls.append(candidate.id)
        if candidate.id == state["fail"]:
            raise bake.RenderError("ffmpeg said no")
        folder = SETTINGS.data_dir / "renders"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{candidate.id}-{preset_key}-{framing}-x.mp4"
        (folder / name).write_bytes(b"0" * 12_000)
        if progress:
            progress("render", 0.5, "half way")
        return {"cached": False, "url": f"/api/renders/{name}", "filename": name, "framing": framing, "style": {"key": preset_key}}

    monkeypatch.setattr(bake, "render_clip", render_clip)
    return calls, state


def test_bake_writes_mp4s_captions_and_a_manifest(source, fake_render, tmp_path):
    calls, _state = fake_render
    result = bake.bake_reel(source, _analysis(source, ["a", "b"]), preset="hormozi", framing="crop")
    folder = Path(result["folder"])
    assert result["baked"] == 2 and result["failed"] == 0
    assert calls == ["a", "b"]
    assert sorted(path.suffix for path in folder.glob("*.mp4")) == [".mp4", ".mp4"]
    assert len(list((folder / "captions").glob("*.srt"))) == 2
    manifest = json.loads((folder / "manifest.json").read_text("utf-8"))
    assert manifest["clip_count"] == 2
    assert manifest["preset"] == "hormozi"
    assert manifest["clips"][0]["file"].endswith(".mp4")
    assert (folder / "README.txt").exists()


def test_a_second_bake_replaces_the_first_instead_of_piling_up(source, fake_render):
    bake.bake_reel(source, _analysis(source, ["a", "b"]))
    folder = Path(bake.bake_dir(source))
    assert len(list(folder.glob("*.mp4"))) == 2
    # A shorter reel must not leave the old second clip behind.
    bake.bake_reel(source, _analysis(source, ["a"]))
    assert len(list(folder.glob("*.mp4"))) == 1


def test_one_failed_clip_does_not_lose_the_others(source, fake_render):
    _calls, state = fake_render
    state["fail"] = "b"
    result = bake.bake_reel(source, _analysis(source, ["a", "b", "c"]))
    assert result["baked"] == 2
    assert result["failed"] == 1
    failed = [clip for clip in result["clips"] if clip.get("error")]
    assert len(failed) == 1 and "ffmpeg said no" in failed[0]["error"]


def test_approved_only_filters_before_rendering(source, fake_render):
    calls, _state = fake_render
    bake.bake_reel(source, _analysis(source, ["a", "b"]), approved_only=True, approved={"b"})
    assert calls == ["b"]


def test_baking_nothing_is_an_error_not_an_empty_folder(source, fake_render):
    with pytest.raises(ValueError):
        bake.bake_reel(source, _analysis(source, []))
