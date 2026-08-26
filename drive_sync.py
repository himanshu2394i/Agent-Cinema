"""Sync .mp4 clips from a shared Google Drive folder into a project.

Hackathon auth is a service account: share the folder with the SA email,
store drive_folder_id on the project, then poll. No user OpenID.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

from projects import (
    CLIP_NAME_RE,
    clips_dir,
    list_projects,
    load_manifest,
    parse_folder_id,
    project_dir,
)

log = logging.getLogger(__name__)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class DriveClient(Protocol):
    def list_mp4s(self, folder_id: str) -> list[dict]:
        """Return [{'id': ..., 'name': ...}, ...] for files in the folder."""

    def download(self, file_id: str, dest: Path) -> None:
        """Write the Drive file bytes to dest."""


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


def try_drive_client() -> DriveClient | None:
    """Build the real Drive client, or None if credentials are missing.

    Prefers a service-account JSON if present. If org policy blocks key
    creation, falls back to Application Default Credentials (gcloud user login
    with the Drive readonly scope).
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
            creds_path, scopes=[DRIVE_SCOPE]
        )
    else:
        try:
            credentials, _ = google_auth_default(scopes=[DRIVE_SCOPE])
        except Exception:
            log.debug("No Drive credentials (JSON key or gcloud ADC)")
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
