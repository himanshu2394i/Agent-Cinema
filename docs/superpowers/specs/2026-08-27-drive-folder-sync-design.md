# Drive folder sync (hackathon)

## Goal

Keep a production’s clip folder in sync with a **team-owned Google Drive folder**, polling every **2 minutes**, without Google login.

## Why this shape

GCP project `devpost-506321` already has Vertex, Cloud Run, IAM, Secret Manager, and Cloud Storage. There is **no** special Drive connector product. The integration is **Google Drive API** + a **service account**. Per-user OpenID (Sign in with Google) is the right path for a full product; out of scope here.

## Auth (option A)

1. Enable `drive.googleapis.com`.
2. Use a service account JSON (`GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_DRIVE_CREDENTIALS`).
3. Share the dailies folder with the SA `client_email` (Viewer is enough).
4. Store `drive_folder_id` on the project `manifest.json` (accept a folder URL and parse the ID).

## Sync behavior

- List files whose parent is that folder; keep `.mp4` names that pass existing clip filename rules.
- Download files that are **not** already in `assets/projects/{id}/clips/`.
- Skip existing names (no overwrite).
- Non-recursive (files in the folder itself).
- Playback stays on `/watch` (not Drive URLs).
- Background: while `projects_api` is running, every **120 seconds** (`DRIVE_SYNC_INTERVAL_SECONDS`) sync every project that has `drive_folder_id`.
- Manual `POST /projects/{id}/drive/sync` for demos.
- If Drive is not configured, skip quietly (API still serves onboard/watch).

## Out of scope

Google login, Shared Drive extras, auto-ingest after download, GCS mirroring.
