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
    screenplay_path,
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
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    name: str


class AttachDrive(BaseModel):
    folder: str


class ProjectStatus(BaseModel):
    id: str
    name: str
    has_vocabulary: bool
    has_screenplay: bool
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
        drive_folder_id = provision_drive_project(body.id.lower(), body.name)
    except Exception:
        log.exception("Drive folder provision failed for %s", body.id)
    return {"id": body.id.lower(), "name": body.name, "drive_folder_id": drive_folder_id}


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
        has_screenplay=screenplay_path(project_id).is_file(),
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


@app.get("/projects/{project_id}/screenplay.pdf")
def api_get_screenplay(project_id: str):
    if not project_dir(project_id).exists():
        raise HTTPException(status_code=404, detail="project not found")
    path = screenplay_path(project_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no screenplay on disk")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/projects/{project_id}/clips")
async def api_upload_clip(project_id: str, file: UploadFile = File(...)) -> dict:
    if not project_dir(project_id).exists():
        raise HTTPException(status_code=404, detail="project not found")
    if not file.filename or not file.filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="upload an mp4 clip")
    target = clips_dir(project_id) / Path(file.filename).name
    target.write_bytes(await file.read())
    pushed = False
    folder_id = load_manifest(project_id).get("drive_folder_id")
    if folder_id:
        drive = try_drive_client()
        if drive is not None:
            drive.upload(target, folder_id)
            pushed = True
    return {"saved": target.name, "uploaded_to_drive": pushed}


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


# The evidence ledger lives in ADK session state, so the panel reads it from
# the agent server rather than keeping a second copy of the truth.
ADK_BASE_URL = os.getenv("ADK_BASE_URL", "http://127.0.0.1:8000")
ADK_APP_NAME = os.getenv("ADK_APP_NAME", "dailies_agent")
NEWLINE = "\n"


def _adk_session(session_id: str, user_id: str, app_name: str) -> dict:
    """Fetch one ADK session, or raise 502/404 with something readable."""
    import urllib.error
    import urllib.parse
    import urllib.request

    url = (
        f"{ADK_BASE_URL.rstrip('/')}/apps/{urllib.parse.quote(app_name)}"
        f"/users/{urllib.parse.quote(user_id)}"
        f"/sessions/{urllib.parse.quote(session_id)}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"no ADK session {session_id!r} for user {user_id!r}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"cannot reach the agent at {ADK_BASE_URL}",
        ) from exc


def _trace_picker_html(user_id: str, app_name: str) -> str:
    """Landing page when no session is named: pick one."""
    sessions = _adk_sessions(user_id, app_name)
    if sessions:
        items = (NEWLINE).join(
            f'      <li><a href="/trace?session={escape(str(item.get("id")))}'
            f'&user={escape(user_id)}">{escape(str(item.get("id")))}</a></li>'
            for item in sessions
        )
        listing = f"<ul class='sessions'>{NEWLINE}{items}{NEWLINE}</ul>"
    else:
        listing = (
            f"<p class='empty'>No sessions found for user"
            f" <code>{escape(user_id)}</code> at {escape(ADK_BASE_URL)}."
            f" Start one in the agent UI, or pass ?user= for a different one.</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investigation &mdash; sessions</title>
  <style>
    body {{ font-family: ui-monospace, Menlo, monospace; background: #0f0f0f;
           color: #ddd; margin: 0; padding: 1.5rem; }}
    main {{ max-width: 46rem; margin: 0 auto; }}
    h1 {{ font-size: 0.85rem; letter-spacing: 0.18em; text-transform: uppercase;
         color: #9cf; border-bottom: 1px solid #333; padding-bottom: 0.6rem; }}
    ul.sessions {{ list-style: none; padding: 0; }}
    ul.sessions li {{ padding: 0.3rem 0; }}
    a {{ color: #9cf; }}
    .empty {{ color: #777; }}
  </style>
</head>
<body>
  <main>
    <h1>Investigation &mdash; pick a session</h1>
    {listing}
  </main>
</body>
</html>
"""


def _adk_sessions(user_id: str, app_name: str) -> list[dict]:
    """Every session for this user, newest first, or [] if the agent is down."""
    import urllib.error
    import urllib.parse
    import urllib.request

    url = (
        f"{ADK_BASE_URL.rstrip('/')}/apps/{urllib.parse.quote(app_name)}"
        f"/users/{urllib.parse.quote(user_id)}/sessions"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            sessions = json.loads(response.read() or b"[]")
    except (OSError, ValueError):
        return []
    if isinstance(sessions, dict):
        sessions = sessions.get("sessions") or []
    return sorted(
        sessions, key=lambda item: item.get("lastUpdateTime") or 0, reverse=True
    )


def _trace_step_html(row: dict) -> str:
    tier = row.get("evidence_tier")
    tier_html = (
        f'<span class="tier {escape(tier.lower())}">{escape(tier.replace("_", " ").lower())}</span>'
        if tier else ""
    )
    clips = (
        f'<div class="clips">{escape(row["clips"])}</div>' if row.get("clips") else ""
    )
    return f"""    <li>
      <div class="head"><span class="tick">&#10003;</span>
        <strong>Step {row['step']} &mdash; {escape(row['label'])}</strong>{tier_html}</div>
      <div class="q">{escape(row['question'])}</div>
      {clips}
      <div class="finding">{escape(row['finding'])}</div>
    </li>"""


@app.get("/trace", response_class=HTMLResponse)
def investigation_trace(
    session: str = Query(None, description="ADK session id"),
    user: str = Query("user", description="ADK user id"),
    app_name: str = Query(None, alias="app", description="ADK app name"),
    turn: str = Query(None, description="Limit to one invocation id"),
):
    """What the agent actually looked at, read back from the evidence ledger.

    Actions, clips, and findings - never the model's reasoning. A judge can
    check every line of this against the footage.
    """
    from dailies_agent.investigation import review, trace_rows

    app_id = app_name or ADK_APP_NAME
    if not session:
        return _trace_picker_html(user, app_id)
    data = _adk_session(session, user, app_id)
    state = data.get("state") or {}
    ledger = state.get("investigation") or []
    rows = trace_rows(ledger, invocation=turn)
    verdict = review(ledger, invocation=turn)

    # The budget is per question, so quoting one over a whole session - which
    # spans many questions - would be a number that means nothing.
    budget_note = (
        f" &middot; budget {verdict['remaining_budget']} left" if turn else ""
    )
    if rows:
        steps_html = "\n".join(_trace_step_html(row) for row in rows)
        body = f"<ol class='steps'>\n{steps_html}\n</ol>"
    else:
        body = (
            "<p class='empty'>No investigation recorded for this session yet."
            " Ask the agent an editorial question, then reload.</p>"
        )

    if not rows:
        footer = ""
    elif verdict["sufficient"]:
        footer = (
            "<p class='verdict ok'><span class='tick'>&#10003;</span>"
            " Evidence sufficient</p>"
        )
    else:
        missing = escape(", ".join(verdict["missing_clips"]))
        gap = escape((verdict["gap"] or "").replace("_", " "))
        footer = (
            f"<p class='verdict gap'>&#9888; Open gap: {gap}"
            f"<br><span class='clips'>not yet inspected: {missing}</span></p>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investigation &mdash; {escape(session)}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
           background: #0f0f0f; color: #ddd; margin: 0; padding: 1.5rem; }}
    main {{ max-width: 46rem; margin: 0 auto; }}
    h1 {{ font-size: 0.85rem; letter-spacing: 0.18em; text-transform: uppercase;
         color: #9cf; border-bottom: 1px solid #333; padding-bottom: 0.6rem; }}
    .meta {{ color: #777; font-size: 0.75rem; margin: -0.5rem 0 1.5rem; }}
    ol.steps {{ list-style: none; padding: 0; margin: 0; }}
    ol.steps li {{ border-left: 2px solid #2c4; padding: 0 0 1.1rem 0.9rem;
                  margin-left: 0.4rem; }}
    .head {{ color: #eee; }}
    .tick {{ color: #2c4; margin-right: 0.4rem; }}
    .q {{ color: #888; font-size: 0.8rem; margin: 0.15rem 0; }}
    .clips {{ color: #9cf; font-size: 0.8rem; margin: 0.2rem 0; }}
    .finding {{ color: #ccc; font-size: 0.82rem; }}
    .tier {{ font-size: 0.68rem; letter-spacing: 0.04em; margin-left: 0.5rem;
            padding: 0.12rem 0.45rem;
            border-radius: 3px; background: #223; color: #9ab; }}
    .tier.direct_interaction {{ background: #12351f; color: #7ddb9b; }}
    .tier.metadata_only {{ background: #3a2612; color: #f0b070; }}
    .verdict {{ margin-top: 0.5rem; padding-top: 0.9rem;
               border-top: 1px solid #333; }}
    .verdict.ok {{ color: #8e8; }}
    .verdict.gap {{ color: #eb8; }}
    .empty {{ color: #777; }}
  </style>
</head>
<body>
  <main>
    <h1>Investigation</h1>
    <p class="meta">session <code>{escape(session)}</code>
      &middot; {len(rows)} step(s){budget_note}
      &middot; <a href="/onboard" style="color:#9cf">onboard</a></p>
    {body}
    {footer}
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
