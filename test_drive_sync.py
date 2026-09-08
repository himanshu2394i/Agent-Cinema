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


def test_try_drive_client_uses_adc_when_no_json_key(monkeypatch):
    import drive_sync

    monkeypatch.delenv("GOOGLE_DRIVE_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    class FakeCreds:
        pass

    monkeypatch.setattr(
        "google.auth.default",
        lambda scopes=None: (FakeCreds(), "devpost-506321"),
    )
    monkeypatch.setattr(
        "googleapiclient.discovery.build",
        lambda *args, **kwargs: object(),
    )
    client = drive_sync.try_drive_client()
    assert client is not None


def test_try_drive_client_uses_saved_oauth_token(tmp_path, monkeypatch):
    import drive_sync

    token = tmp_path / "drive-token.json"
    token.write_text("{}")
    monkeypatch.setenv("GOOGLE_DRIVE_TOKEN", str(token))
    monkeypatch.delenv("GOOGLE_DRIVE_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    class FakeCreds:
        valid = True
        expired = False
        refresh_token = "1//x"

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        lambda *args, **kwargs: FakeCreds(),
    )
    monkeypatch.setattr(
        "google.auth.default",
        lambda scopes=None: (_ for _ in ()).throw(RuntimeError("adc blocked")),
    )
    monkeypatch.setattr(
        "googleapiclient.discovery.build",
        lambda *args, **kwargs: object(),
    )
    assert drive_sync.try_drive_client() is not None


def test_stage_local_dailies_copies_mp4s_into_project_folder(tmp_path):
    from drive_sync import stage_local_dailies

    src = tmp_path / "src"
    src.mkdir()
    (src / "A001_C0001.mp4").write_bytes(b"one")
    (src / "notes.txt").write_text("nope")
    dest = stage_local_dailies("Project1", [src / "A001_C0001.mp4", src / "notes.txt"], root=tmp_path / "dailies")
    assert dest == tmp_path / "dailies" / "Project1"
    assert (dest / "A001_C0001.mp4").read_bytes() == b"one"
    assert not (dest / "notes.txt").exists()


def test_ensure_child_folder_reuses_existing_and_uploads_new_clips():
    from drive_sync import ensure_project_folder, push_clips
    from pathlib import Path

    class FakeWriteDrive:
        def __init__(self):
            self.folders = {("parent", "Project1"): "child-1"}
            self.uploads: list[tuple[str, str]] = []
            self.existing = [{"id": "e1", "name": "A001_C0001.mp4"}]

        def find_child_folder(self, parent_id: str, name: str) -> str | None:
            return self.folders.get((parent_id, name))

        def create_folder(self, parent_id: str, name: str) -> str:
            folder_id = f"new-{name}"
            self.folders[(parent_id, name)] = folder_id
            return folder_id

        def list_mp4s(self, folder_id: str) -> list[dict]:
            return list(self.existing) + [
                {"id": "u", "name": name} for fid, name in self.uploads if fid == folder_id
            ]

        def upload(self, path: Path, folder_id: str) -> None:
            self.uploads.append((folder_id, path.name))

    fake = FakeWriteDrive()
    folder_id = ensure_project_folder(fake, "parent", "Project1")
    assert folder_id == "child-1"
    folder_id = ensure_project_folder(fake, "parent", "Project2")
    assert folder_id == "new-Project2"

    clip_existing = Path("A001_C0001.mp4")
    clip_new = Path("A001_C0002.mp4")
    uploaded = push_clips(fake, "child-1", [clip_existing, clip_new])
    assert uploaded == ["A001_C0002.mp4"]
    assert fake.uploads == [("child-1", "A001_C0002.mp4")]


def test_replace_clips_trashes_existing_then_uploads_all():
    from drive_sync import replace_clips
    from pathlib import Path

    class FakeReplaceDrive:
        def __init__(self):
            self.files = [{"id": "e1", "name": "A001_C0001.mp4"}]
            self.trashed: list[str] = []
            self.uploads: list[str] = []

        def list_mp4s(self, folder_id: str) -> list[dict]:
            live = {item["id"] for item in self.files} - set(self.trashed)
            return [item for item in self.files if item["id"] in live]

        def trash(self, file_id: str) -> None:
            self.trashed.append(file_id)

        def upload(self, path: Path, folder_id: str) -> None:
            self.uploads.append(path.name)
            self.files.append({"id": f"new-{path.name}", "name": path.name})

    fake = FakeReplaceDrive()
    uploaded = replace_clips(
        fake, "child-1", [Path("A001_C0001.mp4"), Path("A001_C0002.mp4")]
    )
    assert fake.trashed == ["e1"]
    assert uploaded == ["A001_C0001.mp4", "A001_C0002.mp4"]
    assert fake.uploads == ["A001_C0001.mp4", "A001_C0002.mp4"]
