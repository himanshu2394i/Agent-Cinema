# Project Onboarding — Design Spec

**Date:** 2026-08-26  
**Status:** Approved for implementation (user selected slices A, B, C)

## Goal

Turn Dailies Triage from a single hardcoded NOTLD demo into a multi-project
product: create a production, upload a screenplay to build its schema, upload
clips to log them, then chat scoped to that project only.

## Phases

| Phase | Delivers |
|---|---|
| **A — Foundation** | `project_id` on every shot row; per-project vocabulary on disk; agent loads vocabulary and filters by project |
| **B — Upload API** | HTTP endpoints to create projects, upload screenplay/clips, trigger ingest |
| **C — Wizard UI** | Simple web wizard (create → screenplay → review vocab → clips → chat) calling the API |

## Architecture

```
Browser wizard (static HTML + fetch)
        │
        ▼
  projects_api.py  (FastAPI, mounted alongside ADK or standalone)
        │
   ┌────┴────┬──────────────┐
   ▼         ▼              ▼
parse_script  ingest_all   vocab.py
   │         │              │
   └────┬────┴──────────────┘
        ▼
   ClickHouse shots (project_id, ...)
        ▼
   ADK agent (vocabulary + prompt scoped to project_id)
```

### Data model

**New column on `shots`:**

```sql
project_id LowCardinality(String)
```

- Existing NOTLD rows get `project_id = 'notld_1968'` via migration/default.
- Synthetic archive rows get `project_id = 'archive'`.
- `ORDER BY` becomes `(project_id, scene, take, start_seconds)`.

**Per-project files** (gitignored under `assets/projects/`):

```
assets/projects/{project_id}/
  manifest.json      # { "name": "...", "created_at": "..." }
  vocabulary.json    # ProjectVocabulary as JSON
  clips/             # uploaded .mp4 files
```

**Default project for backward compatibility:** `notld_1968` reads existing
`assets/vocabulary.json` until migrated.

### Agent scoping

- `dailies_agent/agent.py` reads `PROJECT_ID` env var (default `notld_1968`).
- `demo_vocabulary()` becomes `project_vocabulary(project_id)` — loads from
  `assets/projects/{id}/vocabulary.json`.
- `agent_instruction()` adds: *"Only query rows where project_id = '{id}'."*
- `POPULATION_NOTE` updated: synthetic rows are `project_id = 'archive'`.

### API (Phase B)

| Method | Path | Action |
|---|---|---|
| POST | `/projects` | Create project `{ "id": "my-film", "name": "My Film" }` |
| GET | `/projects` | List projects |
| GET | `/projects/{id}` | Status: vocabulary present?, clip count, shot count |
| POST | `/projects/{id}/screenplay` | Upload PDF → parse → save vocabulary |
| GET | `/projects/{id}/vocabulary` | Return vocabulary JSON |
| POST | `/projects/{id}/clips` | Upload one or more `.mp4` files |
| POST | `/projects/{id}/ingest` | Run ingest for unlogged clips in project |

Ingest and parse reuse existing modules with injected `project_id` on each row.

### Wizard UI (Phase C)

Single static page at `/onboard` (or `static/onboard.html` served by API):

1. **Create project** — id + display name
2. **Upload screenplay** — PDF drag-drop
3. **Review vocabulary** — show characters, locations, props (read-only for v1)
4. **Upload clips** — multi-file mp4
5. **Start logging** — POST ingest, show progress
6. **Open agent** — link to ADK UI with `?project_id=...` (or set cookie)

Styling: minimal, no framework — plain HTML/CSS/JS for hackathon speed.

## Error handling

- Duplicate `project_id` → 409
- Ingest without vocabulary → 400 with clear message
- Gemini/ClickHouse failures → 502 with error type, not stack trace
- Invalid project id (non-slug) → 400

## Testing

- TDD for all new Python: `test_projects.py`, extend `test_shot_schema.py`
- API tests with FastAPI TestClient (no network)
- Existing 84 tests must stay green; migrate fixtures with `project_id`

## Out of scope (v1)

- Auth / multi-user
- GCS upload (local disk + Cloud Run ephemeral volume for demo)
- Survey path for unscripted footage in wizard
- Vocabulary editing UI (read-only review only)
- Continuity checking per project

## Migration

1. Add `project_id` to `MODEL_FIELDS` / DDL / response schema (with default
   handling for ingest).
2. `ALTER TABLE` via existing `alter_statements()`.
3. Backfill: `UPDATE shots SET project_id = 'notld_1968' WHERE source_file LIKE 'A001_%'`.
4. Backfill: `UPDATE shots SET project_id = 'archive' WHERE source_file LIKE 'gs://%'`.
