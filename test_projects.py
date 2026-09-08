import json
import re
from datetime import datetime, timezone

import pytest

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def test_create_project_writes_manifest_and_dirs(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    root = projects.create_project("my-film", "My Film")

    assert root == tmp_path / "my-film"
    assert (root / "clips").is_dir()
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["id"] == "my-film"
    assert manifest["name"] == "My Film"
    assert "created_at" in manifest


def test_create_project_rejects_invalid_slug(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    with pytest.raises(ValueError, match="slug"):
        projects.create_project("My Film!", "x")


def test_create_project_lowercases_slug(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    root = projects.create_project("LailaMajnu", "LailaMajnuMovie")
    assert root.name == "lailamajnu"
    assert json.loads((root / "manifest.json").read_text())["id"] == "lailamajnu"


def test_create_project_rejects_duplicate(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    projects.create_project("alpha", "Alpha")
    with pytest.raises(FileExistsError):
        projects.create_project("alpha", "Alpha again")


def test_list_projects_returns_created_projects(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(projects, "LEGACY_VOCABULARY_PATH", tmp_path / "missing.json")

    projects.create_project("one", "One")
    projects.create_project("two", "Two")

    listed = projects.list_projects()
    assert {p["id"] for p in listed} == {"one", "two"}


def test_vocabulary_path_points_inside_project(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    projects.create_project("notld", "NOTLD")
    assert projects.vocabulary_path("notld") == tmp_path / "notld" / "vocabulary.json"


def test_resolve_clip_finds_project_upload(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    projects.create_project("my-film", "My Film")
    clip = projects.clips_dir("my-film") / "A001_C0007.mp4"
    clip.write_bytes(b"fake-mp4")

    assert projects.resolve_clip("my-film", "A001_C0007.mp4") == clip


def test_resolve_clip_falls_back_to_legacy_assets_clips(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    legacy = tmp_path / "legacy_clips"
    legacy.mkdir()
    (legacy / "A001_C0001.mp4").write_bytes(b"legacy")
    monkeypatch.setattr(projects, "LEGACY_CLIPS_DIR", legacy)

    found = projects.resolve_clip("notld_1968", "A001_C0001.mp4")
    assert found == legacy / "A001_C0001.mp4"


def test_resolve_clip_rejects_path_traversal():
    import projects

    with pytest.raises(ValueError, match="clip"):
        projects.resolve_clip("notld_1968", "../secret.mp4")


def test_clip_watch_url_points_at_viewer():
    import projects

    url = projects.clip_watch_url("A001_C0007.mp4", project_id="my-film",
                                  base_url="http://127.0.0.1:8080")
    assert url == "http://127.0.0.1:8080/watch?project=my-film&file=A001_C0007.mp4"


def test_list_projects_includes_notld_as_a_legacy_entry(tmp_path, monkeypatch):
    """notld_1968 predates the manifest system - its screenplay and clips
    live at the legacy top-level assets/ paths, not assets/projects/<id>/,
    so it has no manifest.json and list_projects() never saw it. That made
    it invisible in the /app picker even though it is a fully-logged, live
    production (180 ClickHouse rows, playable clips) - unlike hackathon,
    project1, and verify_merge_demo, which really do have zero rows.
    resolve_clip() and both vocab.py modules already special-case
    notld_1968 with a legacy-path fallback; list_projects() should too.
    """
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    legacy_vocab = tmp_path / "legacy_vocabulary.json"
    legacy_vocab.write_text("{}")
    monkeypatch.setattr(projects, "LEGACY_VOCABULARY_PATH", legacy_vocab)

    projects.create_project("lailamajnu", "LailaMajnuMovie")

    listed = projects.list_projects()
    assert {p["id"] for p in listed} == {"notld_1968", "lailamajnu"}
    notld = next(p for p in listed if p["id"] == "notld_1968")
    assert notld["name"]


def test_list_projects_skips_notld_when_no_legacy_vocabulary(tmp_path, monkeypatch):
    """A machine with no legacy assets/vocabulary.json (e.g. a fresh clone
    that never ran the NOTLD path) should not advertise a production it
    cannot actually serve."""
    import projects
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(projects, "LEGACY_VOCABULARY_PATH", tmp_path / "missing.json")

    projects.create_project("lailamajnu", "LailaMajnuMovie")

    listed = projects.list_projects()
    assert {p["id"] for p in listed} == {"lailamajnu"}
