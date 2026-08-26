from pathlib import Path

import pytest


def test_parse_folder_id_from_url_and_raw_id():
    from drive_sync import parse_folder_id

    raw = "1AbCDefGhIjk_lmnoPQRS"
    assert parse_folder_id(raw) == raw
    assert (
        parse_folder_id("https://drive.google.com/drive/folders/1AbCDefGhIjk_lmnoPQRS")
        == raw
    )
    assert (
        parse_folder_id(
            "https://drive.google.com/drive/u/0/folders/1AbCDefGhIjk_lmnoPQRS?usp=sharing"
        )
        == raw
    )


def test_parse_folder_id_rejects_garbage():
    from drive_sync import parse_folder_id

    with pytest.raises(ValueError, match="folder"):
        parse_folder_id("not a folder")


def test_set_drive_folder_writes_manifest(tmp_path, monkeypatch):
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    projects.create_project("my-film", "My Film")
    projects.set_drive_folder(
        "my-film", "https://drive.google.com/drive/folders/1AbCDefGhIjk_lmnoPQRS"
    )
    listed = projects.list_projects()
    assert listed[0]["drive_folder_id"] == "1AbCDefGhIjk_lmnoPQRS"


class FakeDrive:
    def __init__(self, files: list[dict], payloads: dict[str, bytes]):
        self.files = files
        self.payloads = payloads
        self.downloads: list[str] = []

    def list_mp4s(self, folder_id: str) -> list[dict]:
        assert folder_id == "1AbCDefGhIjk_lmnoPQRS"
        return list(self.files)

    def download(self, file_id: str, dest: Path) -> None:
        self.downloads.append(file_id)
        dest.write_bytes(self.payloads[file_id])


def test_sync_downloads_new_mp4s_and_skips_existing(tmp_path, monkeypatch):
    import projects
    from drive_sync import sync_project

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    projects.create_project("my-film", "My Film")
    projects.set_drive_folder("my-film", "1AbCDefGhIjk_lmnoPQRS")
    existing = projects.clips_dir("my-film") / "A001_C0001.mp4"
    existing.write_bytes(b"already-here")

    fake = FakeDrive(
        files=[
            {"id": "f1", "name": "A001_C0001.mp4"},
            {"id": "f2", "name": "A001_C0002.mp4"},
            {"id": "f3", "name": "notes.txt"},
            {"id": "f4", "name": "../evil.mp4"},
        ],
        payloads={"f2": b"new-clip"},
    )
    result = sync_project("my-film", drive=fake)

    assert result["downloaded"] == ["A001_C0002.mp4"]
    assert result["skipped"] == ["A001_C0001.mp4"]
    assert fake.downloads == ["f2"]
    assert (projects.clips_dir("my-film") / "A001_C0002.mp4").read_bytes() == b"new-clip"
    assert existing.read_bytes() == b"already-here"


def test_sync_all_projects_only_those_with_folder(tmp_path, monkeypatch):
    import projects
    from drive_sync import sync_all_projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    projects.create_project("linked", "Linked")
    projects.create_project("local-only", "Local")
    projects.set_drive_folder("linked", "1AbCDefGhIjk_lmnoPQRS")

    fake = FakeDrive(
        files=[{"id": "f2", "name": "A001_C0002.mp4"}],
        payloads={"f2": b"clip"},
    )
    results = sync_all_projects(drive=fake)
    assert [r["project_id"] for r in results] == ["linked"]
    assert results[0]["downloaded"] == ["A001_C0002.mp4"]
