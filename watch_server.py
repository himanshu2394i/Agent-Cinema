"""Public HTML5 clip viewer for Cloud Run (CLIP_BASE_URL).

Slim sibling of projects_api: serves /watch and media only so the agent can
cite clickable links without shipping the full onboarding API or Gemini deps.

  uvicorn watch_server:app --host 0.0.0.0 --port 8080
"""

from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from projects import resolve_clip

app = FastAPI(title="Dailies Triage Clip Watch")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/projects/{project_id}/media/{filename}")
def stream_clip(project_id: str, filename: str):
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
    main {{ flex: 1; display: flex; align-items: center; justify-content: center; padding: 1rem; }}
    video {{ max-width: 100%; max-height: calc(100vh - 4rem); background: #000; }}
  </style>
</head>
<body>
  <header>
    <strong>{safe_file}</strong>
    · project <code>{safe_project}</code>
  </header>
  <main>
    <video controls autoplay src="{media}"></video>
  </main>
</body>
</html>
"""


@app.get("/")
def root():
    return {
        "service": "dailies-clips",
        "watch": "/watch?project=notld_1968&file=A001_C0007.mp4",
    }
