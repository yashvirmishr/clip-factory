"""Setup's three questions: is the machine ready, where does scoring look, and
does that address answer. None of these tests touch the network."""

import pytest
from fastapi.testclient import TestClient

from clipper import models, readiness
from clipper.api import app
from clipper.config import SETTINGS
from clipper.llm.scorer import probe_runner


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def keep_runner():
    """Restore the saved runner address, so a test cannot leak into analysis."""
    original = SETTINGS.llama_url
    yield
    SETTINGS.llama_url = original
    models.save()


def test_readiness_answers_in_one_probe(client):
    payload = client.get("/api/readiness").json()
    assert payload["machine"]["tier"] in {"A", "B", "C", "D", "E"}
    assert payload["machine"]["memory_gb"] > 0
    assert payload["machine"]["note"]
    assert isinstance(payload["video"]["ffmpeg"], bool)
    assert payload["speech"]["bin_dir"].endswith("bin")
    assert payload["scoring"]["built_in"] is True
    assert payload["scoring"]["runner"]["source"] in {"env", "config", "none"}
    assert payload["models"]["dir"]


def test_readiness_never_leaks_the_tier_letter_as_a_label(client):
    payload = client.get("/api/readiness").json()
    assert not payload["machine"]["note"].startswith("Tier ")


def test_runner_address_must_be_an_http_url(client):
    for bad in ("ftp://example.com", "example.com:8080", "not a url", "http://"):
        response = client.post("/api/settings/llm", json={"url": bad})
        assert response.status_code == 400, bad


def test_runner_saves_then_clears(client, keep_runner):
    saved = client.post("/api/settings/llm", json={"url": "http://127.0.0.1:9/"})
    assert saved.status_code == 200
    assert saved.json()["url"] == "http://127.0.0.1:9"
    assert saved.json()["source"] == "config"
    assert saved.json()["reachable"] is False

    cleared = client.post("/api/settings/llm", json={"url": ""})
    assert cleared.json()["url"] == ""
    assert cleared.json()["source"] == "none"


def test_runner_test_probes_without_saving(client, keep_runner):
    before = SETTINGS.llama_url
    response = client.post("/api/settings/llm/test", json={"url": "http://127.0.0.1:9"})
    assert response.status_code == 200
    assert response.json()["reachable"] is False
    assert response.json()["error"]
    assert SETTINGS.llama_url == before


def test_environment_owns_the_runner(client, monkeypatch, keep_runner):
    monkeypatch.setenv("CLIPPER_LLAMA_URL", "http://127.0.0.1:8080")
    payload = client.get("/api/settings/llm").json()
    assert payload["source"] == "env"
    assert payload["editable"] is False
    refused = client.post("/api/settings/llm", json={"url": "http://127.0.0.1:9"})
    assert refused.status_code == 409
    assert "CLIPPER_LLAMA_URL" in refused.json()["detail"]


def test_probe_runner_reports_an_unreachable_address_plainly():
    result = probe_runner("http://127.0.0.1:9")
    assert result["reachable"] is False
    assert result["models"] == []
    assert result["error"]


def test_normalize_url_rules():
    assert readiness.normalize_url("") == ""
    assert readiness.normalize_url("http://localhost:8080/") == "http://localhost:8080"
    with pytest.raises(ValueError):
        readiness.normalize_url("http://user:pass@localhost:8080")
