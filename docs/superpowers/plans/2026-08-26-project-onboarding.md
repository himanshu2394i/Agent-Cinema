# Project Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-project onboarding — create a production, upload screenplay + clips, chat scoped to that project.

**Architecture:** `project_id` tags every ClickHouse row; vocabulary lives at `assets/projects/{id}/`; FastAPI endpoints wrap existing parse/ingest; static wizard calls API.

**Tech Stack:** Python 3.12, FastAPI, existing ingest/parse modules, ClickHouse, ADK agent.

## Global Constraints

- Python 3.12; `.venv/Scripts/python.exe -m pytest -q` — never let test count drop below 84.
- TDD: failing test → implement → pass.
- `project_id` is DB-only (not in Gemini schema); set at ingest.
- Slug format: `[a-z0-9][a-z0-9_-]{0,63}`.

---

### Task 1: `projects.py` — create and list projects

**Files:**
- Create: `projects.py`
- Test: `test_projects.py`

**Interfaces:**
- Produces: `create_project(project_id, name) -> Path`, `project_dir(id) -> Path`, `vocabulary_path(id) -> Path`, `list_projects() -> list[dict]`

- [ ] Write failing tests for create/list/duplicate
- [ ] Implement `projects.py`
- [ ] Run `pytest test_projects.py -q`

### Task 2: `project_id` column

**Files:**
- Modify: `shot_schema.py` (DB_ONLY_COLUMNS, agent_instruction project filter)
- Modify: `db.py` (INSERT_COLUMNS, replace_clip scoped by project)
- Modify: `ingest.py` (accept project_id on rows)
- Modify: `synth.py` (project_id='archive' on synthetic rows)
- Test: `test_shot_schema.py`, `test_ingest.py`

### Task 3: Per-project vocabulary loading

**Files:**
- Modify: `vocab.py` — `vocabulary_path_for(project_id)`, migrate default from `assets/vocabulary.json`
- Modify: `dailies_agent/agent.py` — `PROJECT_ID` env var
- Test: `test_vocab.py`

### Task 4: Upload API (`projects_api.py`)

**Files:**
- Create: `projects_api.py` (FastAPI app)
- Test: `test_projects_api.py`
- Add `fastapi` + `python-multipart` to `requirements.txt`

### Task 5: Wizard UI

**Files:**
- Create: `static/onboard.html`
- Mount static files in `projects_api.py`

### Task 6: Wire ingest_all + smoke for project_id

**Files:**
- Modify: `ingest_all.py`, `smoke.py` — `--project` flag default `notld_1968`

### Task 7: Sync `dailies_agent/` bundle + redeploy

**Files:**
- Sync copies, redeploy Cloud Run
