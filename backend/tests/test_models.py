"""Model manager rules: what fits, what is found, what activation persists."""

import pytest

from clipper import hardware, models


@pytest.fixture
def low_memory(monkeypatch):
    monkeypatch.setattr(hardware, "memory_gb", lambda: (16.0, 1.0))
    monkeypatch.setattr(hardware, "probe", lambda: {"memory": {"total_gb": 16.0, "available_gb": 1.0}})


def test_small_models_fit_when_the_machine_is_busy(low_memory):
    # 0.15 GB into 1 GB free is fine; a fixed reserve would wrongly reject it.
    assert models._fits(0.15) is True
    assert models._fits(0.49) is True
    assert models._fits(4.7) is False


def test_fits_uses_at_most_three_quarters_of_free_memory(low_memory):
    assert models._fits(0.74) is True
    assert models._fits(0.76) is False


def test_failed_memory_probe_falls_back_to_half_of_total(monkeypatch):
    monkeypatch.setattr(hardware, "memory_gb", lambda: (16.0, 0.0))
    assert models._available_gb() == pytest.approx(8.0)


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        models.download("no-such-model")


def test_activating_a_model_that_was_never_downloaded_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        models.activate("whisper-base-en")


def test_activating_an_unactivatable_kind_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path)
    model = models.find("silero-vad")
    (tmp_path / model["filename"]).write_bytes(b"\0" * 2048)
    # vad is activatable; a made-up kind must not crash the route either.
    assert models.ACTIVE_KEYS.get("vad")
    with pytest.raises(KeyError):
        models.activate("not-a-model")


def test_find_whisper_cli_prefers_an_explicit_env_path(tmp_path, monkeypatch):
    binary = tmp_path / "whisper-cli.exe"
    binary.write_bytes(b"x")
    monkeypatch.setenv("CLIPPER_WHISPER_CLI", str(binary))
    assert hardware.find_whisper_cli() == str(binary)


def test_find_whisper_cli_searches_a_bin_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPPER_WHISPER_CLI", raising=False)
    binary = tmp_path / "whisper-cli.exe"
    binary.write_bytes(b"x")
    assert hardware.find_whisper_cli([tmp_path]) == str(binary)


def test_find_whisper_cli_reports_nothing_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPPER_WHISPER_CLI", raising=False)
    monkeypatch.setattr(hardware, "WHISPER_BINARIES", ("definitely-not-installed-xyz",))
    assert hardware.find_whisper_cli([tmp_path]) == ""
