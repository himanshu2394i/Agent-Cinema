import json
from io import BytesIO
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import projects
    import projects_api

    monkeypatch.setenv("DRIVE_SYNC_INTERVAL_SECONDS", "0")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(projects_api, "PROJECTS_ROOT", tmp_path)
    return TestClient(projects_api.app)


def test_create_and_list_projects(client):
    response = client.post("/projects", json={"id": "my-film", "name": "My Film"})
    assert response.status_code == 201
    listed = client.get("/projects").json()
    assert listed[0]["id"] == "my-film"


def test_create_project_provisions_drive_subfolder(client, tmp_path, monkeypatch):
    import drive_sync
    import projects

    monkeypatch.setenv("DRIVE_DAILIES_FOLDER_ID", "parentidxxxx")
    monkeypatch.setattr(drive_sync, "DAILIES_ROOT", tmp_path / "dailies")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    class FakeWriteDrive:
        def find_child_folder(self, parent_id, name):
            assert parent_id == "parentidxxxx"
            assert name == "Project2"
            return None

        def create_folder(self, parent_id, name):
            return "childfolder1"

        def list_mp4s(self, folder_id):
            return []

        def upload(self, path, folder_id):
            return None

    monkeypatch.setattr(drive_sync, "try_drive_client", lambda: FakeWriteDrive())
    response = client.post("/projects", json={"id": "project2", "name": "Project2"})
    assert response.status_code == 201
    assert response.json()["drive_folder_id"] == "childfolder1"
    assert (tmp_path / "dailies" / "Project2").is_dir()


def test_upload_screenplay_parses_vocabulary(client, monkeypatch):
    from vocab import ProjectVocabulary

    fake_vocab = ProjectVocabulary.from_raw(
        characters=["Ben"], locations=["Farmhouse"], props=["Rifle"], scenes=[]
    )

    def fake_parse(pdf_bytes, client):
        return fake_vocab

    monkeypatch.setattr("projects_api.parse_screenplay", fake_parse)

    client.post("/projects", json={"id": "notld", "name": "NOTLD"})
    response = client.post(
        "/projects/notld/screenplay",
        files={"file": ("script.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["characters"] == ["Ben"]

    vocab = client.get("/projects/notld/vocabulary").json()
    assert vocab["locations"] == ["Farmhouse"]


def test_serve_and_watch_project_clip(client, tmp_path, monkeypatch):
    import projects
    import projects_api

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(projects_api, "PROJECTS_ROOT", tmp_path)

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    clip_path = projects.clips_dir("demo") / "A001_C0007.mp4"
    clip_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    media = client.get("/projects/demo/media/A001_C0007.mp4")
    assert media.status_code == 200
    assert media.content.startswith(b"\x00\x00")
    assert "video" in media.headers["content-type"]

    watch = client.get("/watch?project=demo&file=A001_C0007.mp4")
    assert watch.status_code == 200
    assert b"<video" in watch.content
    assert b"/projects/demo/media/A001_C0007.mp4" in watch.content


def test_missing_clip_returns_404(client):
    client.post("/projects", json={"id": "empty", "name": "Empty"})
    assert client.get("/projects/empty/media/missing.mp4").status_code == 404


def test_upload_clip_pushes_to_drive_when_folder_linked(client, tmp_path, monkeypatch):
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    client.post("/projects", json={"id": "demo", "name": "Demo"})
    client.post(
        "/projects/demo/drive",
        json={"folder": "https://drive.google.com/drive/folders/1AbCDefGhIjk_lmnoPQRS"},
    )
    uploaded = []

    class FakeDrive:
        def upload(self, path, folder_id):
            uploaded.append((path.name, folder_id))

        def list_mp4s(self, folder_id):
            return []

        def download(self, file_id, dest):
            dest.write_bytes(b"x")

    monkeypatch.setattr("projects_api.try_drive_client", lambda: FakeDrive())
    res = client.post(
        "/projects/demo/clips",
        files={"file": ("A001_C0009.mp4", b"data", "video/mp4")},
    )
    assert res.status_code == 200
    assert res.json()["saved"] == "A001_C0009.mp4"
    assert res.json()["uploaded_to_drive"] is True
    assert uploaded == [("A001_C0009.mp4", "1AbCDefGhIjk_lmnoPQRS")]


def test_attach_drive_folder_and_sync(client, tmp_path, monkeypatch):
    import drive_sync
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(drive_sync, "list_projects", projects.list_projects)
    monkeypatch.setattr(drive_sync, "load_manifest", projects.load_manifest)
    monkeypatch.setattr(drive_sync, "project_dir", projects.project_dir)
    monkeypatch.setattr(drive_sync, "clips_dir", projects.clips_dir)

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    attach = client.post(
        "/projects/demo/drive",
        json={"folder": "https://drive.google.com/drive/folders/1AbCDefGhIjk_lmnoPQRS"},
    )
    assert attach.status_code == 200
    assert attach.json()["drive_folder_id"] == "1AbCDefGhIjk_lmnoPQRS"
    assert client.get("/projects/demo").json()["drive_folder_id"] == "1AbCDefGhIjk_lmnoPQRS"

    class FakeDrive:
        def list_mp4s(self, folder_id):
            return [{"id": "f2", "name": "A001_C0002.mp4"}]

        def download(self, file_id, dest):
            dest.write_bytes(b"clip")

    monkeypatch.setattr("projects_api.try_drive_client", lambda: FakeDrive())
    synced = client.post("/projects/demo/drive/sync")
    assert synced.status_code == 200
    assert synced.json()["downloaded"] == ["A001_C0002.mp4"]
    assert (projects.clips_dir("demo") / "A001_C0002.mp4").is_file()


def test_serve_screenplay_pdf_when_on_disk(client, tmp_path, monkeypatch):
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    client.post("/projects", json={"id": "laila", "name": "Laila"})
    projects.screenplay_path("laila").write_bytes(b"%PDF-1.4 test")

    status = client.get("/projects/laila").json()
    assert status["has_screenplay"] is True

    pdf = client.get("/projects/laila/screenplay.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "pdf" in pdf.headers["content-type"]
