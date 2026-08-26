"""HTTP API for multi-project onboarding and local clip playback.

Run standalone:
    uvicorn projects_api:app --reload --port 8080

Or mount from another ASGI app. Serves /onboard wizard at GET /onboard
and /watch for HTML5 clip playback when the agent cites a source_file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from pydantic import BaseModel, Field

from drive_sync import provision_drive_project, sync_project, try_drive_client
from parse_script import parse_screenplay
from projects import (
    PROJECTS_ROOT,
    clips_dir,
    create_project,
    list_projects,
    load_manifest,
    project_dir,
    resolve_clip,
    set_drive_folder,
    vocabulary_path,
)
from vocab import load_vocabulary

load_dotenv()

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


def _sync_interval_seconds() -> int:
    raw = os.getenv("DRIVE_SYNC_INTERVAL_SECONDS", "120")
    try:
        return int(raw)
    except ValueError:
        return 120


async def _drive_poll_loop(stop: asyncio.Event, interval: int) -> None:
    from drive_sync import sync_all_projects

    while not stop.is_set():
        try:
            await asyncio.to_thread(sync_all_projects)
        except Exception:
            log.exception("background Drive sync failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    interval = _sync_interval_seconds()
    task = None
    if interval > 0:
        task = asyncio.create_task(_drive_poll_loop(stop, interval))
        log.info("Drive folder poll every %s seconds", interval)
    yield
    stop.set()
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Dailies Triage Projects API", lifespan=lifespan)


class CreateProject(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str


class AttachDrive(BaseModel):
    folder: str


class ProjectStatus(BaseModel):
    id: str
    name: str
    has_vocabulary: bool
    clip_count: int
    drive_folder_id: str | None = None


@app.post("/projects", status_code=201)
def api_create_project(body: CreateProject) -> dict:
    try:
        create_project(body.id, body.name)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    drive_folder_id = None
    try:
        drive_folder_id = provision_drive_project(body.id, body.name)
    except Exception:
        log.exception("Drive folder provision failed for %s", body.id)
    return {"id": body.id, "name": body.name, "drive_folder_id": drive_folder_id}


@app.get("/projects")
def api_list_projects() -> list[dict]:
    return list_projects()


@app.get("/projects/{project_id}")
def api_project_status(project_id: str) -> ProjectStatus:
    root = project_dir(project_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="project not found")
    manifest = load_manifest(project_id)
    clips = list(clips_dir(project_id).glob("*.mp4"))
    return ProjectStatus(
        id=project_id,
        name=manifest["name"],
        has_vocabulary=vocabulary_path(project_id).exists(),
        clip_count=len(clips),
        drive_folder_id=manifest.get("drive_folder_id"),
    )


@app.post("/projects/{project_id}/drive")
def api_attach_drive(project_id: str, body: AttachDrive) -> dict:
    try:
        folder_id = set_drive_folder(project_id, body.folder)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": project_id, "drive_folder_id": folder_id}


@app.post("/projects/{project_id}/drive/sync")
def api_sync_drive(project_id: str) -> dict:
    if not project_dir(project_id).exists():
        raise HTTPException(status_code=404, detail="project not found")
    drive = try_drive_client()
    if drive is None:
        raise HTTPException(
            status_code=503,
            detail="Drive is not configured (set GOOGLE_DRIVE_CREDENTIALS)",
        )
    try:
        return sync_project(project_id, drive)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/{project_id}/screenplay")
async def api_upload_screenplay(project_id: str, file: UploadFile = File(...)) -> dict:
    if not project_dir(project_id).exists():
        raise HTTPException(status_code=404, detail="project not found")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="upload a PDF screenplay")

    client = genai.Client()
    vocabulary = parse_screenplay(await file.read(), client)
    vocabulary_path(project_id).write_text(
        json.dumps(
            {
                "characters": vocabulary.characters,
                "locations": vocabulary.locations,
                "props": vocabulary.props,
                "scenes": vocabulary.scenes,
            },
            indent=2,
        )
    )
    return {
        "characters": vocabulary.characters,
        "locations": vocabulary.locations,
        "props": vocabulary.props,
        "scenes": vocabulary.scenes,
    }


@app.get("/projects/{project_id}/vocabulary")
def api_get_vocabulary(project_id: str) -> dict:
    try:
        vocabulary = load_vocabulary(project_id=project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "characters": vocabulary.characters,
        "locations": vocabulary.locations,
        "props": vocabulary.props,
        "scenes": vocabulary.scenes,
    }


@app.post("/projects/{project_id}/clips")
async def api_upload_clip(project_id: str, file: UploadFile = File(...)) -> dict:
    if not project_dir(project_id).exists():
        raise HTTPException(status_code=404, detail="project not found")
    if not file.filename or not file.filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="upload an mp4 clip")
    target = clips_dir(project_id) / Path(file.filename).name
    target.write_bytes(await file.read())
    return {"saved": target.name}


@app.get("/projects/{project_id}/media/{filename}")
def api_stream_clip(project_id: str, filename: str):
    """Stream an mp4 for the HTML5 viewer (and direct download)."""
    try:
        path = resolve_clip(project_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/watch", response_class=HTMLResponse)
def watch_clip(
    file: str = Query(..., description="source_file basename, e.g. A001_C0007.mp4"),
    project: str = Query("notld_1968", description="project_id"),
):
    """Simple HTML5 player so ADK answers can link to a watchable clip."""
    try:
        path = resolve_clip(project, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="clip not found")
    safe_file = escape(path.name)
    safe_project = escape(project)
    media = f"/projects/{safe_project}/media/{safe_file}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_file} — Dailies Triage</title>
  <style>
    :root {{ font-family: system-ui, sans-serif; color: #111; background: #0f0f0f; }}
    body {{ margin: 0; min-height: 100vh; display: flex; flex-direction: column; }}
    header {{ padding: 0.75rem 1rem; color: #eee; background: #1a1a1a; }}
    header a {{ color: #9cf; }}
    main {{ flex: 1; display: flex; align-items: center; justify-content: center; padding: 1rem; }}
    video {{ max-width: 100%; max-height: calc(100vh - 4rem); background: #000; }}
  </style>
</head>
<body>
  <header>
    <strong>{safe_file}</strong>
    · project <code>{safe_project}</code>
    · <a href="/onboard">onboard</a>
  </header>
  <main>
    <video controls autoplay src="{media}"></video>
  </main>
</body>
</html>
"""


@app.get("/onboard")
def onboard_page():
    page = STATIC / "onboard.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="onboard.html missing")
    return FileResponse(page)


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
