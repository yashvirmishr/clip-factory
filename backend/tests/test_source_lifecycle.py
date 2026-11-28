"""Removing and relinking sources without orphaning clips or deleting user media."""

import shutil
import uuid

import pytest
from fastapi.testclient import TestClient

from clipper import db, demo, service
from clipper.api import app
from clipper.config import SETTINGS


@pytest.fixture(scope="module")
def demo_file():
    return demo.generate(SETTINGS.media_dir() / "lifecycle", seconds=4)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def managed_copy(demo_file):
    target = demo_file.parent / f"managed-{uuid.uuid4().hex}.mp4"
    shutil.copyfile(demo_file, target)
    return target


def test_the_list_says_which_files_are_present(clean_db, demo_file):
    source = service.ingest(demo_file, "Lifecycle")
    row = next(item for item in db.list_sources_with_stats() if item["id"] == source.id)
    assert row["available"] is True
    assert row["deletable"] is True


def test_forgetting_a_source_keeps_the_file_by_default(clean_db, demo_file):
    source = service.ingest(demo_file, "Lifecycle")
    thumbs = SETTINGS.artifacts_dir() / source.id / "thumbs"
    thumbs.mkdir(parents=True)
    (thumbs / "frame.jpg").write_bytes(b"jpeg")

    result = service.forget(source)

    assert result["file_deleted"] is False
    assert db.get_source(source.id) is None
    assert demo_file.exists()
    assert not (SETTINGS.artifacts_dir() / source.id).exists()


def test_deleting_media_only_touches_the_managed_copy(clean_db, demo_file):
    copy = managed_copy(demo_file)
    source = service.ingest(copy, "Managed")

    result = service.forget(source, delete_file=True)

    assert result["file_deleted"] is True
    assert result["warnings"] == []
    assert not copy.exists()
    assert demo_file.exists()


def test_a_file_outside_the_media_folder_is_never_deleted(clean_db, demo_file, tmp_path):
    outside = tmp_path / "outside.mp4"
    shutil.copyfile(demo_file, outside)
    source = service.ingest(outside, "Outside")

    result = service.forget(source, delete_file=True)

    assert result["file_deleted"] is False
    assert outside.exists()
    assert any("outside" in warning for warning in result["warnings"])


def test_forgetting_clears_the_analysis_and_clip_edits(clean_db, demo_file):
    source = service.ingest(demo_file, "Lifecycle")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO analyses (source_id, payload, asr_backend, llm_backend, created_at)"
            " VALUES (?,?,?,?,?)",
            (source.id, "{}", "stub", "heuristic", 0.0),
        )
        conn.execute(
            "INSERT INTO clip_edits (source_id, clip_id, kind, payload, updated_at)"
            " VALUES (?,?,?,?,?)",
            (source.id, "clip-1", "trim", "{}", 0.0),
        )

    service.forget(source)

    assert db.has_analysis(source.id) is False
    with db.connect() as conn:
        rows = conn.execute("SELECT 1 FROM clip_edits WHERE source_id=?", (source.id,)).fetchall()
    assert rows == []


def test_relink_points_the_source_at_the_moved_file(clean_db, demo_file, tmp_path):
    source = service.ingest(demo_file, "Lifecycle")
    moved = tmp_path / "moved.mp4"
    shutil.copyfile(demo_file, moved)

    updated = service.relink(source, moved)

    assert updated.id == source.id
    assert updated.path == str(moved.resolve())
    assert db.get_source(source.id).path == str(moved.resolve())


def test_relink_refuses_a_file_of_a_different_length(clean_db, demo_file):
    source = service.ingest(demo_file, "Lifecycle")
    other = demo.generate(SETTINGS.media_dir() / "lifecycle-long", seconds=90)

    with pytest.raises(ValueError, match="long"):
        service.relink(source, other)

    assert db.get_source(source.id).path == str(demo_file.resolve())


def test_relink_reports_a_missing_file(clean_db, demo_file):
    source = service.ingest(demo_file, "Lifecycle")
    with pytest.raises(FileNotFoundError):
        service.relink(source, demo_file.parent / "not-there.mp4")


def test_the_api_removes_a_source(client, clean_db, demo_file):
    source = service.ingest(demo_file, "Lifecycle")
    response = client.delete(f"/api/sources/{source.id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert db.get_source(source.id) is None


def test_the_api_relinks_a_source(client, clean_db, demo_file, tmp_path):
    source = service.ingest(demo_file, "Lifecycle")
    moved = tmp_path / "api-moved.mp4"
    shutil.copyfile(demo_file, moved)
    response = client.post(
        f"/api/sources/{source.id}/relink", json={"path": str(moved)}
    )
    assert response.status_code == 200
    assert response.json()["path"] == str(moved.resolve())


def test_unknown_sources_are_a_404(client):
    assert client.delete("/api/sources/missing").status_code == 404
    assert client.post("/api/sources/missing/relink", json={"path": "x"}).status_code == 404
