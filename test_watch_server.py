"""Tests for the slim Cloud Run clip watch server."""

from pathlib import Path

from fastapi.testclient import TestClient

import projects
import watch_server


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
