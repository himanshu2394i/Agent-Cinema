"""Tests for the slim Cloud Run clip watch server."""

import io
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

import projects
import watch_server


class FakeBlob:
    """Stand-in for google.cloud.storage.Blob — no real network calls."""

    def __init__(self, data: bytes | None):
        self._data = data
        self.size = len(data) if data is not None else None

    def exists(self):
        return self._data is not None

    def reload(self):
        pass

    def open(self, mode):
        assert mode == "rb"
        return io.BytesIO(self._data)


def test_watch_returns_html5_video(tmp_path, monkeypatch):
    legacy = tmp_path / "clips"
    legacy.mkdir()
    (legacy / "A001_C0007.mp4").write_bytes(b"fake-mp4")
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", legacy)
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")

    client = TestClient(watch_server.app)
    res = client.get("/watch?project=notld_1968&file=A001_C0007.mp4")
    assert res.status_code == 200
    assert "video" in res.text
    assert "/projects/notld_1968/media/A001_C0007.mp4" in res.text


def test_media_streams_mp4(tmp_path, monkeypatch):
    legacy = tmp_path / "clips"
    legacy.mkdir()
    (legacy / "A001_C0007.mp4").write_bytes(b"fake-mp4-bytes")
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", legacy)
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")

    client = TestClient(watch_server.app)
    res = client.get("/projects/notld_1968/media/A001_C0007.mp4")
    assert res.status_code == 200
    assert res.content == b"fake-mp4-bytes"
    assert "video/mp4" in res.headers["content-type"]


def test_watch_page_renders_when_clip_only_in_gcs(tmp_path, monkeypatch):
    """The agent cites /watch links; they must not 404 just because the
    clip isn't staged in the container image (see resolve_clip callers)."""
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("GCS_INGEST_BUCKET", "test-bucket")

    client = TestClient(watch_server.app)
    res = client.get("/watch?project=lailamajnu&file=A001_C0001.mp4")
    assert res.status_code == 200
    assert "/projects/lailamajnu/media/A001_C0001.mp4" in res.text


def test_watch_404_when_missing_locally_and_no_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.delenv("GCS_INGEST_BUCKET", raising=False)

    client = TestClient(watch_server.app)
    res = client.get("/watch?project=lailamajnu&file=A001_C0001.mp4")
    assert res.status_code == 404


def test_media_prefers_local_disk_over_gcs(tmp_path, monkeypatch):
    """Local disk wins even when a bucket is configured — no GCS call made."""
    clips = tmp_path / "projects" / "lailamajnu" / "clips"
    clips.mkdir(parents=True)
    (clips / "A001_C0001.mp4").write_bytes(b"local-bytes")
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("GCS_INGEST_BUCKET", "test-bucket")

    def fail_if_called(bucket, blob_name):
        raise AssertionError("must not hit GCS when the file exists locally")

    monkeypatch.setattr(watch_server, "_gcs_blob", fail_if_called)

    client = TestClient(watch_server.app)
    res = client.get("/projects/lailamajnu/media/A001_C0001.mp4")
    assert res.status_code == 200
    assert res.content == b"local-bytes"


def test_media_falls_back_to_gcs_when_missing_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("GCS_INGEST_BUCKET", "test-bucket")

    calls = {}

    def fake_gcs_blob(bucket, blob_name):
        calls["bucket"] = bucket
        calls["blob_name"] = blob_name
        return FakeBlob(b"gcs-bytes")

    monkeypatch.setattr(watch_server, "_gcs_blob", fake_gcs_blob)

    client = TestClient(watch_server.app)
    res = client.get("/projects/lailamajnu/media/A001_C0001.mp4")
    assert res.status_code == 200
    assert res.content == b"gcs-bytes"
    assert calls == {"bucket": "test-bucket", "blob_name": "lailamajnu/A001_C0001.mp4"}


def test_media_gcs_range_request_returns_206(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("GCS_INGEST_BUCKET", "test-bucket")
    monkeypatch.setattr(watch_server, "_gcs_blob", lambda b, n: FakeBlob(b"0123456789"))

    client = TestClient(watch_server.app)
    res = client.get(
        "/projects/lailamajnu/media/A001_C0001.mp4",
        headers={"Range": "bytes=2-5"},
    )
    assert res.status_code == 206
    assert res.content == b"2345"
    assert res.headers["content-range"] == "bytes 2-5/10"


def test_media_404_when_missing_everywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.delenv("GCS_INGEST_BUCKET", raising=False)

    client = TestClient(watch_server.app)
    res = client.get("/projects/lailamajnu/media/A001_C0001.mp4")
    assert res.status_code == 404


def test_media_404_when_missing_locally_and_in_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("GCS_INGEST_BUCKET", "test-bucket")
    monkeypatch.setattr(watch_server, "_gcs_blob", lambda b, n: FakeBlob(None))

    client = TestClient(watch_server.app)
    res = client.get("/projects/lailamajnu/media/A001_C0001.mp4")
    assert res.status_code == 404


def test_media_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path / "projects")

    client = TestClient(watch_server.app)
    traversal_name = quote("..\\..\\secret.mp4", safe="")
    res = client.get(f"/projects/notld_1968/media/{traversal_name}")
    assert res.status_code == 400
