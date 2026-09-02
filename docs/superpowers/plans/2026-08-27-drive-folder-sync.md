# Drive Folder Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poll a shared Drive folder every 2 minutes and copy new `.mp4`s into the project clips directory.

**Architecture:** `drive_sync.py` lists/downloads via an injectable Drive client; `projects.py` stores `drive_folder_id` on the manifest; FastAPI lifespan runs the interval loop; wizard attaches a folder URL.

**Tech Stack:** Google Drive API v3, `google-api-python-client`, FastAPI background task, pytest fakes (no live Drive).

## Global Constraints

- Vertex-only agent; no AI Studio switch.
- No Google login / OpenID in this slice.
- Do not commit service-account JSON or `.env`.
- Clip names must still pass `CLIP_NAME_RE`.
- Default poll interval 120 seconds.

---

### Task 1: Folder ID + manifest + fake sync

- Create: `drive_sync.py`, `test_drive_sync.py`
- Modify: `projects.py`, `test_projects.py`

### Task 2: API + background poll + wizard

- Modify: `projects_api.py`, `test_projects_api.py`, `static/onboard.html`, `requirements.txt`, `.env.example`, `README.md`
