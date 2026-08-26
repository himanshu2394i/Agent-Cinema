# Dailies Triage

An assistant editor that watches your footage and lets you ask for shots in
plain English.

> *"Which takes of scene 14B have Ben holding the tyre iron, before dark?"*

## The problem

Every shooting day produces hours of footage. Someone watches all of it
overnight and writes down what is in each clip - who is in frame, how close
the camera is, whether the take was usable. That is called logging, it is done
by hand, and it is the reason nobody can find anything three weeks later.

## How it works

    SCREENPLAY (pdf)
          |  Gemini extracts the cast, locations and props
          v
    PROJECT VOCABULARY  ------------------+
          |                               |
          v                               v
    FOOTAGE --> Gemini logs each shot   AGENT PROMPT
                against that vocabulary   |
          |                               |
          v                               |
      ClickHouse  <--- MCP ---------------+
                       (official mcp-clickhouse server)

The screenplay is the schema. Every production names its own characters,
locations and props, so the vocabulary is generated per project rather than
hardcoded - and because the same vocabulary constrains what Gemini may write
and tells the agent what it may filter on, the two cannot drift apart.

That matters more than it sounds. If the logger writes `"wide shot"` and the
agent filters for `'wide'`, every query returns nothing while every component
reports success. One field table in `shot_schema.py` generates the Gemini
response schema, the ClickHouse DDL and the agent's prompt, and
`test_shot_schema.py` fails if the DDL and response schema ever cover
different fields. That test compares field names, not the allowed values for
each field, so it is not a full guarantee against drift by itself.

Retrieval is deliberately not vector search. Shots are structured rows in
ClickHouse, and the agent writes real SQL against them through the official
`mcp-clickhouse` MCP server - an editor hunting a specific take needs complete
results, not approximately-similar ones.

## Layout

| File | What it does |
|---|---|
| `vocab.py` | Fixed cinematographic vocabulary + the per-project one |
| `parse_script.py` | Screenplay PDF to vocabulary (the Gemini call) |
| `run_parse.py` | Standalone CLI: parse a screenplay PDF and print the vocabulary |
| `shot_schema.py` | The one field table, and the three artefacts it generates |
| `ingest.py` | One clip to validated shot rows |
| `clips.py` | Cuts a feature into camera-roll-named clips, via ffmpeg |
| `ingest_all.py` | Batch ingest a directory of clips, one at a time |
| `survey.py` | Proposes a vocabulary from footage that has no screenplay |
| `continuity.py` | Compares one character's state across a location |
| `synth.py` | Synthetic dailies, for testing search at archive scale |
| `db.py` | ClickHouse connection, schema, bulk load |
| `projects.py` / `projects_api.py` | Multi-project onboarding + clip watch API |
| `static/onboard.html` | Wizard: create project → screenplay → clips |
| `dailies_agent/` | The ADK agent (queries ClickHouse over MCP) |
| `smoke.py` | Whole pipeline in one run: screenplay -> vocabulary -> clip -> ClickHouse |

## Running it

Prerequisites: Python 3.12, a Google Cloud / Gemini API credential, a
ClickHouse Cloud service, and (only for `clips.py`) `ffmpeg`/`ffprobe` on
your PATH.

    python -m venv .venv
    .venv/Scripts/python.exe -m pip install -r requirements.txt
    cp .env.example .env    # then fill in your Gemini and ClickHouse Cloud values

`assets/` is gitignored, so a fresh clone has no screenplay and no footage.
Both of ours are public domain — *Night of the Living Dead* (1968), whose
copyright notice was omitted on release:

    mkdir assets
    curl -L -o assets/notld_1968_screenplay.pdf "https://archive.org/download/night-of-the-living-dead-1990-1989.02.00-1st/Night%20of%20the%20Living%20Dead%20%281968%29%20%5BRusso%20draft%5D_text.pdf"
    curl -L -o assets/notld_full.mp4 "https://archive.org/download/Night.Of.The.Living.Dead_1080p/NightOfTheLivingDead_DVD5_512kb.mp4"

The film is 334 MB. Cut it into stand-in dailies — a finished feature has no
takes and no slate, but its shots are real photography with real coverage,
which is what the logger needs to be tested against:

    .venv/Scripts/python.exe clips.py assets/notld_full.mp4 assets/clips 20 45

Then log one clip end to end, and open the agent:

    .venv/Scripts/python.exe db.py init
    .venv/Scripts/python.exe smoke.py assets/notld_1968_screenplay.pdf assets/clips/A001_C0001.mp4
    .venv/Scripts/adk.exe web

`smoke.py` must run before `adk web`: it writes `assets/vocabulary.json`, and
the agent builds its system prompt from that file at import time. Without it
you get a `FileNotFoundError` naming the missing file.

`adk web` reads `dailies_agent/` from the current directory, so run it from
the project root. Its first run on a machine asks (once) whether to enable
anonymous telemetry. Once it's up, open http://127.0.0.1:8000 and ask it a
question about the footage you just logged.

`smoke.py` logs one clip. To log the whole directory you cut earlier:

    .venv/Scripts/python.exe ingest_all.py assets/clips

That skips any clip already in the table, so re-running after a failure costs
one Gemini call per clip still missing rather than one per clip in the
directory — which matters, because the free tier allows twenty requests per
day per model. Pass `--force` to re-log everything anyway. Scope a batch to a
project with `--project my-film` (default `notld_1968`).

## Multi-project onboarding

Create a production, upload a screenplay and clips, then chat scoped to that
project:

    .venv/Scripts/python.exe -m uvicorn projects_api:app --reload --port 8080

Open http://127.0.0.1:8080/onboard. After clips are on disk (upload or Drive
sync), ingest from the CLI the wizard shows, set `PROJECT_ID` in `.env` to
your project slug, and run `adk web`.

### Google Drive folder (ongoing dailies)

GCP often blocks service-account JSON keys
(`iam.disableServiceAccountKeyCreation`). For the hackathon, log in as yourself:

    gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly

Keep `uvicorn projects_api` running — it polls every 2 minutes
(`DRIVE_SYNC_INTERVAL_SECONDS`) and copies new `.mp4` files into
`assets/projects/{id}/clips/`. Paste the folder URL in the onboarding wizard
(use a folder your Google account can already open). Or:

    curl -X POST http://127.0.0.1:8080/projects/my-film/drive -H "Content-Type: application/json" -d "{\"folder\":\"https://drive.google.com/drive/folders/FILE_ID\"}"

## Watching clips the agent cites

Keep the projects API running on port 8080 while you chat. The agent is
instructed to cite real `source_file` values as markdown watch links, e.g.
`http://127.0.0.1:8080/watch?project=notld_1968&file=A001_C0007.mp4`. That
page plays the mp4 from `assets/projects/{id}/clips/` (or the legacy
`assets/clips/` folder for `notld_1968`). Override the link base with
`CLIP_BASE_URL` if the API is not on localhost:8080.

## Tests

    .venv/Scripts/python.exe -m pytest -q

The suite passes from a clean clone with nothing installed but
`requirements.txt` — no `.env`, no credentials, no assets. That is the point:
every Gemini and ClickHouse call in the tests goes through a hand-written fake
client rather than the real SDKs, so the whole pipeline is testable without a
key or a live database.

## Hackathon deploy

See **`docs/HACKATHON_CHECKLIST.md`** for the full submission checklist and
**`docs/DEPLOY.md`** for Vertex AI + Cloud Run deployment (you have GCP
credits now). Quick path:

    # Vertex in .env, then:
    .venv/Scripts/adk.exe deploy cloud_run --project=YOUR_PROJECT --region=us-central1 --service_name=dailies-agent --with_ui dailies_agent

Use a read-only ClickHouse user for the deployed agent; SQL is in `docs/DEPLOY.md`.

## Credits

Test assets are *Night of the Living Dead* (1968), public domain.
