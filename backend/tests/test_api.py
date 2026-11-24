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


def test_health(client):
    payload = client.get("/api/health").json()
    assert payload["ok"] is True
    assert "data_dir" in payload


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
