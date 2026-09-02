"""Public HTML5 clip viewer for Cloud Run (CLIP_BASE_URL).

Slim sibling of projects_api: serves /watch and media only so the agent can
cite clickable links without shipping the full onboarding API or Gemini deps.

  uvicorn watch_server:app --host 0.0.0.0 --port 8080
"""

import os
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from projects import _safe_clip_name, resolve_clip

app = FastAPI(title="Dailies Triage Clip Watch")

_GCS_READ_CHUNK = 1024 * 1024  # stream in 1 MiB pieces; never buffer a whole clip


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


def _gcs_blob(bucket: str, blob_name: str):
    """Lazy import so the module still imports with no GCS installed/configured."""
    from google.cloud import storage

    return storage.Client().bucket(bucket).blob(blob_name)


def _parse_range(range_header: str, size: int) -> tuple[int, int]:
    """Parse a single-range 'bytes=START-END' header. Raises ValueError if unsatisfiable."""
    units, _, rng = range_header.partition("=")
    if units.strip() != "bytes":
        raise ValueError(f"unsupported range unit: {range_header!r}")
    start_s, _, end_s = rng.partition("-")
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else size - 1
    if start > end or start >= size or start < 0:
        raise ValueError(f"range not satisfiable: {range_header!r}")
    return start, min(end, size - 1)


def _stream_from_gcs(bucket: str, blob_name: str, range_header: str | None):
    """Stream a clip out of GCS, honouring Range for player seeking. None if not found."""
    blob = _gcs_blob(bucket, blob_name)
    if not blob.exists():
        return None
    blob.reload()
    size = blob.size

    status_code = 200
    start, end = 0, size - 1
    headers = {"Accept-Ranges": "bytes"}
    if range_header:
        try:
            start, end = _parse_range(range_header, size)
        except ValueError:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)

    def chunks():
        stream = blob.open("rb")
        try:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = stream.read(min(_GCS_READ_CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data
        finally:
            stream.close()

    return StreamingResponse(
        chunks(), status_code=status_code, media_type="video/mp4", headers=headers
    )


@app.get("/projects/{project_id}/media/{filename}")
def stream_clip(project_id: str, filename: str, request: Request):
    try:
        path = resolve_clip(project_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path is not None:
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    bucket = os.environ.get("GCS_INGEST_BUCKET")
    if bucket:
        safe_name = _safe_clip_name(filename)
        response = _stream_from_gcs(
            bucket, f"{project_id}/{safe_name}", request.headers.get("range")
        )
        if response is not None:
            return response

    raise HTTPException(status_code=404, detail="clip not found (checked local disk and GCS)")


@app.get("/watch", response_class=HTMLResponse)
def watch_clip(
    file: str = Query(..., description="source_file basename, e.g. A001_C0007.mp4"),
    project: str = Query("notld_1968", description="project_id"),
):
    try:
        path = resolve_clip(project, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path is not None:
        safe_file = escape(path.name)
    elif os.environ.get("GCS_INGEST_BUCKET"):
        # Not staged in the image, but the media route can still serve it
        # from GCS - don't 404 the page itself for a valid, GCS-backed clip.
        safe_file = escape(_safe_clip_name(file))
    else:
        raise HTTPException(status_code=404, detail="clip not found")
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
