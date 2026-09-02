"""Sync .mp4 clips from a shared Google Drive folder into a project.

Hackathon auth: Desktop OAuth (`python drive_sync.py login`) because org
policy blocks SA keys and Google blocks gcloud ADC for Drive scopes.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Protocol

from projects import (
    CLIP_NAME_RE,
    clips_dir,
    list_projects,
    load_manifest,
    parse_folder_id,
    project_dir,
    set_drive_folder,
)

log = logging.getLogger(__name__)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DRIVE_SCOPES = [DRIVE_SCOPE]
DAILIES_ROOT = Path("assets/dailies")
FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveClient(Protocol):
    def list_mp4s(self, folder_id: str) -> list[dict]:
        """Return [{'id': ..., 'name': ...}, ...] for files in the folder."""

    def download(self, file_id: str, dest: Path) -> None:
        """Write the Drive file bytes to dest."""

    def find_child_folder(self, parent_id: str, name: str) -> str | None:
        ...

    def create_folder(self, parent_id: str, name: str) -> str:
        ...

    def upload(self, path: Path, folder_id: str) -> None:
        ...

    def trash(self, file_id: str) -> None:
        """Move a Drive file to trash."""


def stage_local_dailies(
    folder_name: str, sources: list[Path], root: Path | None = None
) -> Path:
    """Copy safe .mp4s into assets/dailies/{folder_name}/ (or a test root)."""
    dest = (root if root is not None else DAILIES_ROOT) / folder_name
    dest.mkdir(parents=True, exist_ok=True)
    for src in sources:
        name = _safe_clip_name(src.name)
        if name is None or not src.is_file():
            continue
        shutil.copy2(src, dest / name)
    return dest


def ensure_project_folder(drive: DriveClient, parent_id: str, name: str) -> str:
    existing = drive.find_child_folder(parent_id, name)
    if existing:
        return existing
    return drive.create_folder(parent_id, name)


def provision_drive_project(
    project_id: str,
    folder_name: str,
    drive: DriveClient | None = None,
    parent_id: str | None = None,
) -> str | None:
    """Create assets/dailies/{name} and a matching Drive folder under the parent."""
    parent = parent_id or os.getenv("DRIVE_DAILIES_FOLDER_ID", "").strip()
    if not parent:
        return None
    client = drive if drive is not None else try_drive_client()
    if client is None:
        DAILIES_ROOT.joinpath(folder_name).mkdir(parents=True, exist_ok=True)
        return None
    DAILIES_ROOT.joinpath(folder_name).mkdir(parents=True, exist_ok=True)
    child = ensure_project_folder(client, parent, folder_name)
    set_drive_folder(project_id, child)
    return child


def push_clips(drive: DriveClient, folder_id: str, paths: list[Path]) -> list[str]:
    existing = {item.get("name") for item in drive.list_mp4s(folder_id)}
    uploaded: list[str] = []
    for path in paths:
        name = _safe_clip_name(path.name)
        if name is None or name in existing:
            continue
        drive.upload(path, folder_id)
        uploaded.append(name)
        existing.add(name)
    return uploaded


def replace_clips(drive: DriveClient, folder_id: str, paths: list[Path]) -> list[str]:
    """Trash mp4s already in the folder, then upload every local clip.

    `push_clips` skips names that already exist, which is correct for an
    incremental sync and wrong after a recut that reuses camera-roll names.
    """
    for item in drive.list_mp4s(folder_id):
        file_id = item.get("id")
        if file_id:
            drive.trash(file_id)
    return push_clips(drive, folder_id, paths)


def _safe_clip_name(name: str) -> str | None:
    normalized = (name or "").replace("\\", "/")
    if "/" in normalized or ".." in normalized:
        return None
    if not CLIP_NAME_RE.match(normalized):
        return None
    return normalized


def sync_project(project_id: str, drive: DriveClient) -> dict:
    """Download new mp4s for one project. Skip names already on disk."""
    if not project_dir(project_id).exists():
        raise FileNotFoundError(f"project {project_id!r} not found")
    folder_id = load_manifest(project_id).get("drive_folder_id")
    if not folder_id:
        raise ValueError(f"project {project_id!r} has no drive_folder_id")

    dest_dir = clips_dir(project_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    skipped: list[str] = []

    for item in drive.list_mp4s(folder_id):
        name = _safe_clip_name(item.get("name") or "")
        if name is None:
            continue
        dest = dest_dir / name
        if dest.exists():
            skipped.append(name)
            continue
        drive.download(item["id"], dest)
        downloaded.append(name)

    return {
        "project_id": project_id,
        "folder_id": folder_id,
        "downloaded": downloaded,
        "skipped": skipped,
    }


def sync_all_projects(drive: DriveClient | None = None) -> list[dict]:
    """Sync every project that has a drive_folder_id. No-op if Drive is unset."""
    client = drive if drive is not None else try_drive_client()
    if client is None:
        return []
    results = []
    for project in list_projects():
        if not project.get("drive_folder_id"):
            continue
        try:
            results.append(sync_project(project["id"], client))
        except Exception:
            log.exception("Drive sync failed for %s", project["id"])
    return results


def _load_oauth_token():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = Path(os.getenv("GOOGLE_DRIVE_TOKEN", ".adk/drive-token.json"))
    if not path.is_file():
        return None
    creds = Credentials.from_authorized_user_file(str(path), DRIVE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json())
    if creds and creds.valid:
        return creds
    return None


def login() -> None:
    """One-time browser login using this GCP project's Desktop OAuth client.

    gcloud ADC is blocked for Drive ('This app is blocked'). Use a Desktop
    OAuth client from APIs & Services → Credentials, with the consent screen
    in Testing and your Google account added as a test user.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_path = Path(os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT", "client_secret.json"))
    if not client_path.is_file():
        raise FileNotFoundError(
            f"OAuth client JSON not found at {client_path}. "
            "Create a Desktop OAuth client in GCP and download it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), DRIVE_SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    token_path = Path(os.getenv("GOOGLE_DRIVE_TOKEN", ".adk/drive-token.json"))
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Saved Drive token to {token_path}")


def try_drive_client() -> DriveClient | None:
    """Build the real Drive client, or None if credentials are missing.

    Order: service-account JSON → saved OAuth token → gcloud ADC.
    """
    try:
        from google.auth import default as google_auth_default
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        log.debug("google-api-python-client not installed; skipping Drive sync")
        return None

    credentials = None
    creds_path = os.getenv("GOOGLE_DRIVE_CREDENTIALS") or os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    if creds_path and Path(creds_path).is_file():
        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=DRIVE_SCOPES
        )
    if credentials is None:
        try:
            credentials = _load_oauth_token()
        except Exception:
            log.debug("Saved Drive OAuth token not usable")
            credentials = None
    if credentials is None:
        try:
            credentials, _ = google_auth_default(scopes=DRIVE_SCOPES)
        except Exception:
            log.debug("No Drive credentials (OAuth token, JSON key, or ADC)")
            return None

    if credentials is None:
        return None
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return GoogleDriveClient(service, MediaIoBaseDownload)


class GoogleDriveClient:
    def __init__(self, service, media_download_cls):
        self.service = service
        self._media_download_cls = media_download_cls

    def list_mp4s(self, folder_id: str) -> list[dict]:
        query = f"'{folder_id}' in parents and trashed = false"
        files: list[dict] = []
        page_token = None
        while True:
            response = (
                self.service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            files.extend(response.get("files") or [])
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return files

    def download(self, file_id: str, dest: Path) -> None:
        request = self.service.files().get_media(fileId=file_id)
        with dest.open("wb") as handle:
            downloader = self._media_download_cls(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    def find_child_folder(self, parent_id: str, name: str) -> str | None:
        query = (
            f"'{parent_id}' in parents and name = '{name}' "
            f"and mimeType = '{FOLDER_MIME}' and trashed = false"
        )
        response = (
            self.service.files()
            .list(
                q=query,
                fields="files(id, name)",
                pageSize=10,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = response.get("files") or []
        return files[0]["id"] if files else None

    def create_folder(self, parent_id: str, name: str) -> str:
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        created = (
            self.service.files()
            .create(body=body, fields="id", supportsAllDrives=True)
            .execute()
        )
        return created["id"]

    def upload(self, path: Path, folder_id: str) -> None:
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)
        body = {"name": path.name, "parents": [folder_id]}
        self.service.files().create(
            body=body, media_body=media, fields="id", supportsAllDrives=True
        ).execute()

    def trash(self, file_id: str) -> None:
        self.service.files().update(
            fileId=file_id,
            body={"trashed": True},
            supportsAllDrives=True,
        ).execute()


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if args == ["login"]:
        login()
    elif args[:1] == ["bootstrap"] and len(args) >= 2:
        from projects import clips_dir, create_project, set_drive_folder

        folder_name = args[1]
        parent = os.getenv("DRIVE_DAILIES_FOLDER_ID", "")
        if not parent:
            raise SystemExit("Set DRIVE_DAILIES_FOLDER_ID to the parent dailies folder id")
        source_dir = Path(args[2]) if len(args) > 2 else Path("assets/clips")
        sources = sorted(source_dir.glob("*.mp4"))
        local = stage_local_dailies(folder_name, sources)
        slug = folder_name.lower()
        try:
            create_project(slug, folder_name)
        except FileExistsError:
            pass
        for clip in local.glob("*.mp4"):
            shutil.copy2(clip, clips_dir(slug) / clip.name)
        drive = try_drive_client()
        if drive is None:
            raise SystemExit("Run: python drive_sync.py login  (must allow Drive edit)")
        child = ensure_project_folder(drive, parent, folder_name)
        set_drive_folder(slug, child)
        uploaded = push_clips(drive, child, sorted(local.glob("*.mp4")))
        print(f"local={local} drive_folder={child} uploaded={len(uploaded)}")
    elif args[:1] == ["replace-clips"] and len(args) >= 2:
        project_id = args[1]
        drive = try_drive_client()
        if drive is None:
            raise SystemExit("Run: python drive_sync.py login  (must allow Drive edit)")
        folder_id = load_manifest(project_id).get("drive_folder_id")
        if not folder_id:
            raise SystemExit(f"project {project_id!r} has no drive_folder_id")
        paths = sorted(clips_dir(project_id).glob("*.mp4"))
        if not paths:
            raise SystemExit(f"no mp4s in {clips_dir(project_id)}")
        uploaded = replace_clips(drive, folder_id, paths)
        print(f"trashed+uploaded={len(uploaded)} local={len(paths)} folder={folder_id}")
    else:
        raise SystemExit(
            "Usage: python drive_sync.py login"
            " | python drive_sync.py bootstrap Project1 [assets/clips]"
            " | python drive_sync.py replace-clips PROJECT_ID"
        )
