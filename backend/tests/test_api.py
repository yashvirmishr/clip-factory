import json
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from clipper import db, demo, service
from clipper.api import app
from clipper.config import SETTINGS
from clipper.domain import LLMJudgement


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def analyzed(client):
    path = demo.generate(SETTINGS.media_dir(), seconds=45)
    source = service.ingest(path, "Demo stream")
    result = service.analyze(source, limit=4, force=True)
    return source, result


def word_groups(captions: dict) -> list[list[dict]]:
    return [
        [
            {"text": word["text"], "start": word["start"], "end": word["end"]}
            for word in page["words"]
        ]
        for page in captions["pages"]
    ]


def test_health(client):
    payload = client.get("/api/health").json()
    assert payload["ok"] is True
    assert "data_dir" in payload


def test_diagnostics_snapshot(client):
    payload = client.get("/api/diagnostics").json()
    assert payload["version"]
    assert payload["data_dir"]
    assert payload["db"]["bytes"] >= 0
    assert payload["data_writable"] is True
    assert isinstance(payload["jobs"], list)
    assert payload["uptime_s"] >= 0


def test_hardware_probe_returns_a_tier_and_models(client):
    payload = client.get("/api/hardware").json()
    assert payload["advice"]["tier"] in {"A", "B", "C", "D", "E"}
    assert payload["profile"]["memory"]["total_gb"] > 0
    assert payload["advice"]["asr"] is not None
    assert payload["advice"]["llm_scoring"] is not None
    assert any(m["kind"] == "vad" for m in payload["models"])


def test_sources_round_trip(client, analyzed):
    source, _ = analyzed
    listed = client.get("/api/sources").json()
    assert any(item["id"] == source.id for item in listed)
    single = client.get(f"/api/sources/{source.id}").json()
    assert single["duration"] > 0


def test_missing_source_is_404(client):
    assert client.get("/api/sources/nope").status_code == 404


def test_analysis_is_served_and_has_ranked_clips(client, analyzed):
    source, _ = analyzed
    payload = client.get(f"/api/sources/{source.id}/analysis").json()
    assert payload["candidates"]
    ranked = [c for c in payload["candidates"] if c["rank"]]
    assert ranked
    assert all(c["scorecard"] for c in ranked)
    assert all(g["id"] for c in ranked for g in c["gates"])


def test_reel_shape_drops_word_timings_and_stays_small(client, analyzed):
    source, _ = analyzed
    reel = client.get(f"/api/sources/{source.id}/analysis").json()
    assert reel["candidates"]
    assert all("words" not in clip for clip in reel["candidates"])
    assert all(clip["rank"] for clip in reel["candidates"])
    assert len(json.dumps(reel).encode("utf-8")) < 64_000

    full = client.get(f"/api/sources/{source.id}/analysis?shape=full").json()
    assert any(c["words"] for c in full["candidates"] if c["rank"])


def test_source_list_reports_counts_without_reading_payloads(client, analyzed):
    source, _ = analyzed
    row = next(r for r in client.get("/api/sources").json() if r["id"] == source.id)
    assert row["analyzed"] is True
    assert row["clip_count"] >= 1
    assert row["reel_quality"] > 0


def test_caption_edit_round_trips_and_can_be_reset(client, analyzed):
    source, _ = analyzed
    analysis = client.get(f"/api/sources/{source.id}/analysis").json()
    clip = next(c for c in analysis["candidates"] if c["rank"])
    url = f"/api/sources/{source.id}/clips/{clip['id']}/captions"

    base = client.get(url).json()
    assert base["edited"] is False
    assert base["pages"]
    pages = word_groups(base)
    pages[0][0]["text"] = "edited"

    saved = client.put(url, json={"pages": pages})
    assert saved.status_code == 200
    body = saved.json()
    assert body["edited"] is True
    assert body["pages"][0]["text"].startswith("edited")

    stored = client.get(url).json()
    assert stored["edited"] is True
    assert stored["pages"][0]["text"].startswith("edited")

    reset = client.delete(url)
    assert reset.status_code == 200
    assert reset.json()["edited"] is False
    assert reset.json()["pages"][0]["text"] == base["pages"][0]["text"]


def test_clip_subtitles_download_as_sidecars(client, analyzed):
    source, _ = analyzed
    analysis = client.get(f"/api/sources/{source.id}/analysis").json()
    clip = next(c for c in analysis["candidates"] if c["rank"])
    base = f"/api/sources/{source.id}/clips/{clip['id']}/subtitles"

    vtt = client.get(f"{base}?format=vtt")
    assert vtt.status_code == 200
    assert vtt.text.startswith("WEBVTT")
    assert "-->" in vtt.text

    srt = client.get(f"{base}?format=srt")
    assert srt.status_code == 200
    assert "-->" in srt.text and "WEBVTT" not in srt.text

    ass = client.get(f"{base}?format=ass")
    assert ass.status_code == 200
    assert "[V4+ Styles]" in ass.text

    assert client.get(f"{base}?format=docx").status_code == 400


def test_reel_subtitles_are_a_zip(client, analyzed):
    source, _ = analyzed
    response = client.get(f"/api/sources/{source.id}/subtitles?format=vtt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert names and all(name.endswith(".vtt") for name in names)
        assert archive.read(names[0]).decode("utf-8").startswith("WEBVTT")


def test_fonts_endpoint_offers_families_and_script_hints(client):
    payload = client.get("/api/fonts").json()
    assert payload["families"]
    assert "latin" in payload["curated"]
    assert payload["curated"]["thai"]


def test_render_presets_are_a_full_catalogue(client):
    presets = client.get("/api/render/presets").json()
    assert presets
    for preset in presets:
        assert {"key", "label", "font", "size", "margin_v", "karaoke"} <= set(preset)


def test_caption_edit_rejects_an_empty_page_list(client, analyzed):
    source, _ = analyzed
    analysis = client.get(f"/api/sources/{source.id}/analysis").json()
    clip = next(c for c in analysis["candidates"] if c["rank"])
    response = client.put(
        f"/api/sources/{source.id}/clips/{clip['id']}/captions",
        json={"pages": []},
    )
    assert response.status_code == 400


def test_peaks_endpoint_returns_downsampled_waveform(client, analyzed):
    source, _ = analyzed
    payload = client.get(f"/api/sources/{source.id}/peaks?buckets=200").json()
    assert payload["buckets"] == 200
    assert len(payload["low"]) == 200 == len(payload["high"])
    assert payload["duration"] > 0


def test_media_endpoint_serves_the_source_file(client, analyzed):
    source, _ = analyzed
    response = client.get(f"/api/media/{source.id}")
    assert response.status_code == 200
    assert len(response.content) > 1000


def test_decision_records_feedback_and_reports_learning(client, analyzed):
    source, result = analyzed
    clip = next(c for c in result.candidates if c.rank)
    response = client.post(
        f"/api/sources/{source.id}/clips/{clip.id}/decision",
        json={"action": "approve", "reason": ""},
    )
    payload = response.json()
    assert payload["ok"] is True
    assert payload["state"]["decisions"] >= 1
    assert 0.0 <= payload["state"]["progress_to_ranker"] <= 1.0
    assert payload["state"]["learning_threshold"] >= 1


def test_reject_requires_valid_action(client, analyzed):
    source, result = analyzed
    clip = next(c for c in result.candidates if c.rank)
    bad = client.post(
        f"/api/sources/{source.id}/clips/{clip.id}/decision",
        json={"action": "banana"},
    )
    assert bad.status_code == 400


def test_hook_edit_is_persisted_and_feeds_the_profile(client, analyzed):
    source, result = analyzed
    clip = next(c for c in result.candidates if c.rank)
    new_hook = "the controller exploded live"
    response = client.post(
        f"/api/sources/{source.id}/clips/{clip.id}/hook", json={"hook": new_hook}
    )
    assert response.json()["hook"] == new_hook
    refreshed = client.get(f"/api/sources/{source.id}/analysis").json()
    updated = next(c for c in refreshed["candidates"] if c["id"] == clip.id)
    assert updated["llm"]["hook"] == new_hook


def test_training_export_is_valid_jsonl(client, analyzed):
    source, result = analyzed
    clip = next(c for c in result.candidates if c.rank)
    client.post(f"/api/sources/{source.id}/clips/{clip.id}/hook", json={"hook": "edited hook"})
    body = client.get("/api/learn/export").text
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert lines
    for line in lines:
        assert json.loads(line)["type"] in {"sft", "dpo"}


def test_learn_state_exposes_the_full_loop(client, analyzed):
    state = client.get("/api/learn/state").json()
    assert "decisions" in state
    assert "ranker_active" in state
    assert "style_profile" in state
    assert isinstance(state["features"], list) and state["features"]
    assert "quality" in state


def test_ffmpeg_probe_reports_libass(client):
    payload = client.get("/api/ffmpeg").json()
    assert payload["available"] is True
    assert payload["libass"] is True


def test_trim_moves_the_bounds_and_recuts_the_transcript(client, analyzed):
    source, result = analyzed
    clip = next(c for c in result.candidates if c.rank and c.duration > 10)
    new_start = clip.start + 1.5
    new_end = clip.end - 1.0
    caption_url = f"/api/sources/{source.id}/clips/{clip.id}/captions"
    base = client.get(caption_url).json()
    assert client.put(caption_url, json={"pages": word_groups(base)}).status_code == 200

    payload = client.post(
        f"/api/sources/{source.id}/clips/{clip.id}/trim",
        json={"start": new_start, "end": new_end},
    ).json()
    assert payload["start"] == pytest.approx(new_start, abs=1e-3)
    assert payload["end"] == pytest.approx(new_end, abs=1e-3)
    # Words outside the new window are gone, and every surviving word is inside it.
    assert payload["words"]
    assert all(w["start"] >= new_start - 1e-3 and w["end"] <= new_end + 1e-3 for w in payload["words"])
    assert payload["text"] == " ".join(w["text"] for w in payload["words"])

    refreshed = client.get(f"/api/sources/{source.id}/analysis").json()
    stored = next(c for c in refreshed["candidates"] if c["id"] == clip.id)
    assert stored["start"] == pytest.approx(new_start, abs=1e-3)
    # Page timings were written against the old bounds; trimming drops them.
    assert client.get(caption_url).json()["edited"] is False


def test_trim_refuses_to_make_an_unusable_clip(client, analyzed):
    source, result = analyzed
    clip = next(c for c in result.candidates if c.rank)
    payload = client.post(
        f"/api/sources/{source.id}/clips/{clip.id}/trim",
        json={"start": clip.end - 1.0, "end": clip.end},
    ).json()
    # Clamped to the minimum usable length instead of accepting a 1 s clip.
    assert payload["end"] - payload["start"] >= 4.9


def test_trim_rejects_a_missing_clip(client, analyzed):
    source, _ = analyzed
    response = client.post(
        f"/api/sources/{source.id}/clips/nope/trim", json={"start": 1, "end": 9}
    )
    assert response.status_code == 404


def test_framing_endpoint_returns_a_plan_or_explains_its_absence(client, analyzed):
    source, result = analyzed
    clip = next(c for c in result.candidates if c.rank)
    payload = client.get(f"/api/sources/{source.id}/clips/{clip.id}/framing").json()
    assert isinstance(payload["cuts"], list)
    assert payload["shots"]
    if payload["plan"] is not None:
        assert payload["plan"]["crop_w"] > 0
        assert payload["plan"]["knots"]
        assert payload["expression"]


def test_export_serves_each_editor_format(client, analyzed):
    source, _ = analyzed
    expectations = {
        "otio": "application/json",
        "fcpxml": "application/xml",
        "edl": "text/plain",
        "srt": "text/plain",
        "bundle": "application/zip",
    }
    for fmt, media_type in expectations.items():
        response = client.get(f"/api/sources/{source.id}/export?format={fmt}")
        assert response.status_code == 200, fmt
        assert response.headers["content-type"].startswith(media_type)
        assert "attachment" in response.headers["content-disposition"]
        assert len(response.content) > 100


def test_approved_only_export_filters_and_refuses_an_empty_selection(client, analyzed, monkeypatch):
    source, _ = analyzed
    url = f"/api/sources/{source.id}/export?format=bundle&approved_only=true"
    analysis = client.get(f"/api/sources/{source.id}/analysis").json()
    clip = next(c for c in analysis["candidates"] if c["rank"])

    monkeypatch.setattr("clipper.api._approved_ids", lambda: set())
    assert client.get(url).status_code == 400

    monkeypatch.setattr("clipper.api._approved_ids", lambda: {clip["id"]})
    exported = client.get(url)
    assert exported.status_code == 200
    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["clip_count"] == 1


def test_export_bundle_has_the_edit_decision_list_and_captions(client, analyzed):
    source, result = analyzed
    payload = client.get(f"/api/sources/{source.id}/export?format=bundle").content
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "reel.otio" in names and "reel.xml" in names and "reel.edl" in names
        manifest = json.loads(archive.read("manifest.json"))
        ranked = [c for c in result.candidates if c.rank]
        assert manifest["clip_count"] == len(ranked)
        assert manifest["media_embedded"] is False
        assert any(n.startswith("captions/") for n in names)


def test_export_rejects_an_unknown_format(client, analyzed):
    source, _ = analyzed
    assert client.get(f"/api/sources/{source.id}/export?format=premiere9").status_code == 400


def test_models_endpoint_reports_installed_and_fit(client):
    payload = client.get("/api/models").json()
    assert payload["tier"] in {"A", "B", "C", "D", "E"}
    assert payload["models"]
    entry = payload["models"][0]
    for field in ("id", "kind", "label", "size_gb", "installed", "active", "fits"):
        assert field in entry
    assert payload["available_gb"] >= 0
    assert set(payload["active"]) >= {"asr", "vad", "llm"}


def test_downloading_an_unknown_model_is_a_404(client):
    assert client.post("/api/models/not-a-model/download").status_code == 404


def test_activating_a_model_that_is_not_downloaded_is_refused(client):
    response = client.post("/api/models/qwen2.5-14b-q4/activate")
    assert response.status_code == 409
    assert "download" in response.json()["detail"]


def test_activation_persists_to_config_json(client, tmp_path, monkeypatch):
    from clipper import models

    model = models.find("whisper-small-en")
    staged = models.models_dir() / model["filename"]
    staged.write_bytes(b"\0" * 4096)
    try:
        response = client.post("/api/models/whisper-small-en/activate").json()
        assert response["ok"] is True
        assert response["active"]["asr"] == str(staged)

        # It has to survive a restart, which means it has to be on disk.
        saved = json.loads((SETTINGS.data_dir / "config.json").read_text("utf-8"))
        assert saved["whisper_model_path"] == str(staged)

        # And be re-applied when settings are loaded again.
        from clipper.config import Settings, _apply_overrides

        reloaded = _apply_overrides(Settings(), saved)
        assert reloaded.whisper_model_path == str(staged)
    finally:
        staged.unlink(missing_ok=True)
        staged.with_suffix(staged.suffix + ".sha256").unlink(missing_ok=True)
        (SETTINGS.data_dir / "config.json").unlink(missing_ok=True)


def test_chat_status_is_reported_for_a_source_without_chat(client, analyzed):
    source, _ = analyzed
    payload = client.get(f"/api/sources/{source.id}/chat").json()
    assert payload["available"] is False
    assert payload["messages"] == 0
    assert payload["twitch_vod"] == ""


def test_chat_fetch_refuses_a_source_that_is_not_a_twitch_vod(client, analyzed):
    source, _ = analyzed
    response = client.post(f"/api/sources/{source.id}/chat/fetch", json={})
    assert response.status_code == 400
    assert "twitch.tv/videos" in response.json()["detail"]


def test_a_stored_chat_replay_reaches_the_analysis(client, analyzed):
    """The point of the artifact: re-analysis scores chat instead of dropping it."""
    from clipper.pipeline import chat as chatmod

    source, _ = analyzed
    target = service.artifacts_for(source.id) / service.CHAT_FILE
    chatmod.write_dump(target, [10.0] * 90 + [20.0] * 90)

    payload = client.get(f"/api/sources/{source.id}/chat").json()
    assert payload["available"] is True
    assert payload["messages"] == 180

    result = service.analyze(source, limit=2, force=True)
    assert not any("No chat replay" in warning for warning in result.warnings)
    assert max(candidate.signals["chat"] for candidate in result.candidates) > 0


def test_url_ingest_rejects_a_local_path(client):
    response = client.post("/api/sources/url", json={"path": "C:/media/stream.mp4"})
    assert response.status_code == 400
    assert "http" in response.json()["detail"]


def test_ingest_accepts_a_url_without_touching_the_network(client, monkeypatch):
    """The service must route URLs to the fetcher, not to the file probe."""
    from clipper.pipeline import fetch

    calls = {}

    def fake_fetch(url, out_dir, progress=None, max_height=1080, timeout=0):
        calls["url"] = url
        video = SETTINGS.media_dir() / "fetched.mp4"
        demo.generate(SETTINGS.media_dir(), seconds=30)
        (SETTINGS.media_dir() / "demo-stream.mp4").replace(video)
        return fetch.Fetched(path=video, title="Fetched stream", duration=30.0, video_id="x", url=url)

    monkeypatch.setattr(fetch, "fetch", fake_fetch)
    source = service.ingest("https://example.com/vod/1")
    assert calls["url"] == "https://example.com/vod/1"
    assert source.name == "Fetched stream"
    assert source.duration > 0
    # The URL is kept: chat replay is fetched later, long after ingest.
    assert source.origin_url == "https://example.com/vod/1"


def test_caption_style_round_trips_into_the_ass_download(client, analyzed):
    """A saved per-clip style must reach the burner, not just the studio."""
    source, result = analyzed
    clip = next(candidate for candidate in result.candidates if candidate.rank)
    base = f"/api/sources/{source.id}/clips/{clip.id}"

    response = client.put(
        f"{base}/captions/style",
        json={"preset": "hormozi", "overrides": {"font": "Impact", "size": 77, "song": "no"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["font"] == "Impact"
    assert body["size"] == 77
    # Unknown keys are dropped on the way in, so a stale client cannot poison it.
    assert body["overrides"] == {"font": "Impact", "size": 77}

    loaded = client.get(f"{base}/captions/style?preset=hormozi").json()
    assert loaded["size"] == 77

    ass = client.get(f"{base}/subtitles?format=ass").text
    assert "Clip,Impact,77," in ass

    cleared = client.delete(f"{base}/captions/style?preset=hormozi")
    assert cleared.status_code == 200
    assert cleared.json()["overrides"] == {}
    assert cleared.json()["font"] != "Impact"
    assert "Impact" not in client.get(f"{base}/subtitles?format=ass").text


def test_each_clip_keeps_its_own_caption_preset(client, analyzed):
    """The preset is part of the clip, not a global preference."""
    source, result = analyzed
    clips = [candidate for candidate in result.candidates if candidate.rank][:2]
    assert len(clips) == 2
    first, second = (f"/api/sources/{source.id}/clips/{clip.id}" for clip in clips)

    assert client.put(f"{first}/captions/style", json={"preset": "box", "overrides": {}}).status_code == 200
    assert (
        client.put(
            f"{second}/captions/style", json={"preset": "neon", "overrides": {"size": 90}}
        ).status_code
        == 200
    )

    one = client.get(f"{first}/captions/style").json()
    two = client.get(f"{second}/captions/style").json()
    assert one["preset"] == "box"
    assert two["preset"] == "neon"
    assert two["size"] == 90
    # The download follows the clip, not the caller's default.
    assert "Arial Black" in client.get(f"{first}/subtitles?format=ass").text
    assert "Segoe UI Semibold" in client.get(f"{second}/subtitles?format=ass").text

    applied = client.put(
        f"{first}/captions/style",
        json={"preset": "minimal", "overrides": {"size": 70}, "apply_to_all": True},
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] >= 2
    assert client.get(f"{second}/captions/style").json()["preset"] == "minimal"


def test_bake_endpoint_runs_a_job_and_serves_the_folder(client, analyzed, monkeypatch):
    import json as json_module
    import time as time_module

    from clipper.editors import bake as bake_module

    source, _result = analyzed
    folder = bake_module.bake_dir(source)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "01 clip.mp4").write_bytes(b"0" * 2048)
    (folder / "manifest.json").write_text(
        json_module.dumps({"clip_count": 1, "baked": 1, "failed": 0, "clips": []}), "utf-8"
    )

    def fake_bake(source_, analysis_, **kwargs):
        return {
            "folder": str(folder),
            "clip_count": 1,
            "baked": 1,
            "failed": 0,
            "clips": [{"id": "x", "name": "01 clip", "file": "01 clip.mp4"}],
        }

    monkeypatch.setattr(bake_module, "bake_reel", fake_bake)
    started = client.post(f"/api/sources/{source.id}/export/bake", json={})
    assert started.status_code == 200
    job_id = started.json()["id"]
    payload = started.json()
    for _ in range(80):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"done", "error"}:
            break
        time_module.sleep(0.05)
    assert payload["status"] == "done"
    assert payload["analysis"]["baked"] == 1

    manifest = client.get(f"/api/sources/{source.id}/export/bake").json()
    assert manifest["exists"] is True
    served = client.get(f"/api/sources/{source.id}/export/bake/file/01 clip.mp4")
    assert served.status_code == 200
    assert served.content == b"0" * 2048
    assert client.get(f"/api/sources/{source.id}/export/bake/file/nope.mp4").status_code == 404


def test_job_events_streams_the_result_and_then_closes(client):
    """The stream must end on the terminal frame; a client cannot be left hanging."""
    import time as time_module

    from clipper.api import JOBS

    job = JOBS.submit("render", lambda progress: {"ok": True, "filename": "x.mp4"})
    settled = False
    for _ in range(200):
        if client.get(f"/api/jobs/{job.id}").json()["status"] == "done":
            settled = True
            break
        time_module.sleep(0.01)
    assert settled, "the trivial job did not finish; the stream test would hang"

    frames: list[str] = []
    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                frames.append(line[6:])
    assert frames, "a finished job still has to send its result"
    final = json.loads(frames[-1])
    assert final["status"] == "done"
    assert final["analysis"] == {"ok": True, "filename": "x.mp4"}

    assert client.get("/api/jobs/nope/events").status_code == 404


def test_job_events_and_the_poll_route_agree(client):
    """One payload builder: the two routes must not drift apart."""
    import time as time_module

    from clipper.api import JOBS

    job = JOBS.submit("render", lambda progress: {"style": "hormozi"})
    for _ in range(200):
        polled = client.get(f"/api/jobs/{job.id}").json()
        if polled["status"] == "done":
            break
        time_module.sleep(0.01)
    streamed: dict = {}
    with client.stream("GET", f"/api/jobs/{job.id}/events") as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                streamed = json.loads(line[6:])
    assert streamed["analysis"] == polled["analysis"]
    assert streamed["status"] == polled["status"]


def test_reveal_refuses_anything_outside_the_exports_tree(client, tmp_path):
    outside = client.post("/api/reveal", json={"path": str(tmp_path)})
    assert outside.status_code == 403
    assert "bake" in outside.json()["detail"]

    from clipper.editors.bake import bakes_root

    missing = bakes_root() / "not-baked-yet"
    assert client.post("/api/reveal", json={"path": str(missing)}).status_code == 404


def test_reveal_opens_a_bake_folder(client, monkeypatch):
    from clipper.editors import bake as bake_module

    folder = bake_module.bakes_root() / "reveal-src"
    folder.mkdir(parents=True, exist_ok=True)
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda path: opened.append(path), raising=False)
    response = client.post("/api/reveal", json={"path": str(folder)})
    assert response.status_code == 200
    if opened:  # POSIX uses xdg-open/open instead of startfile
        assert opened[0] == str(folder.resolve())


def test_framing_status_reports_the_managed_face_model(client):
    payload = client.get("/api/framing/status").json()
    assert payload["engine"] in ("opencv-yunet", "activity")
    assert payload["model_installed"] is False
    assert payload["model_id"] == "face-yunet"
    assert payload["configured"] is False
    assert payload["hint"]


def test_caption_style_rejects_an_unknown_clip(client, analyzed):
    source, _result = analyzed
    response = client.put(
        f"/api/sources/{source.id}/clips/nope/captions/style", json={"overrides": {"size": 90}}
    )
    assert response.status_code == 404
