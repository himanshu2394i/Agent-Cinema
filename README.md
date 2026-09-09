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

## Decisions and tradeoffs

**Structured SQL over vector search.** An editor hunting one take needs every
matching row, not nearest neighbours. ClickHouse holds typed shot columns;
the agent writes real `SELECT`s through the official `mcp-clickhouse` MCP
server (read-only, with query timeouts). We trade semantic fuzzy match for
complete, filterable answers — and for the ability to explain *why* a query
returned nothing.

**Screenplay as schema, not a hardcoded cast list.** Every production names
its own characters, locations, and props. Gemini parses the PDF once into a
per-project vocabulary; that same vocabulary constrains what ingest may write
and what the agent may filter on. The cost is incompleteness: a minor
character barely named in the script can be missing from the enum even when
they appear on camera.

**Closed enums + open prose (prefer `unknown` over a wrong name).** When the
camera shows someone the vocabulary never listed, the logger must not invent
a cast member to satisfy the schema. Enum fields may return `unknown`; free-
text `action` / `dialogue` still capture what was seen. Editors forgive empty
results; they do not forgive a shot labelled with the wrong actor. The Judy
row in *Night of the Living Dead* is the worked example: `characters: ['Tom',
'unknown']` beside an action line that names her — findable via prose search
when the enum cannot.

**One field table, three artefacts.** `shot_schema.py` generates the Gemini
response schema, the ClickHouse DDL, and the agent prompt from one source.
A test fails if DDL and response schema cover different field names. That is
not a full anti-drift guarantee: it does not check that allowed *values* stay
aligned across prompt and rows.

**Official MCP over a bespoke ClickHouse wrapper.** The agent talks to
ClickHouse the same way any MCP client would. That keeps the demo honest for
the ClickHouse track and avoids a private query layer that only this repo
understands. The tradeoff is dependency discipline: ADK needs `mcp<2`, so
`mcp-clickhouse` is pinned to `0.4.1` — newer releases pull `mcp>=2` and break
the Cloud Run image build.

**Finished features as stand-in dailies.** Real multi-take dailies with slates
were not available. Public-domain features cut into camera-roll-named clips
give real photography and coverage for logging tests, but not take numbers or
scene slates — so `scene` is often `unknown` on purpose. Mismatched
vocabulary vs footage (e.g. legend geography vs Kashmir locations) is left
visible in the rows rather than papered over.

**Skip already-logged clips on re-ingest.** Gemini quota is finite. After a
partial batch failure, re-running the whole directory would re-spend calls on
clips already safely in ClickHouse. `ingest_all.py` checks what is logged and
skips it unless `--force` is passed.

**Public chat, locked onboarding.** The judging URL must stay open for
`/app`, sessions, and ask. Create / upload / Drive / ingest and `/onboard`
are gated behind `ONBOARD_TOKEN` (unset on Cloud Run → 404) so strangers
cannot overwrite vocabularies or burn paid Gemini calls. Local unlock:
`ONBOARD_TOKEN=…` and `/onboard?token=…`.

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

The same trick runs a second production, `lailamajnu`, whose vocabulary comes
from an original short screenplay of the public-domain Layla and Majnun legend
(`scripts/write_laila_screenplay.py`) while its footage is stand-in clips cut
from a feature. Worth knowing what that does to the logs, because it is
visible in the rows: the *cast* transfers, because the film is an adaptation
of the same legend, so `characters` comes back `Laila`, `Qays`, `Children`
rather than `unknown`. The *geography* does not - the legend says Desert Camp
and Kaaba, the film is set in Kashmir, so `location` is `unknown` on every
row. `scene` is `unknown` too, as it is for any finished feature: no slate.
That gap is the honest shape of a vocabulary and a corpus that do not share a
production, and it is worth saying out loud in a demo rather than letting a
viewer find it.

Then log one clip end to end, and start the agent's API server:

    .venv/Scripts/python.exe db.py init
    .venv/Scripts/python.exe smoke.py assets/notld_1968_screenplay.pdf assets/clips/A001_C0001.mp4
    .venv/Scripts/adk.exe api_server

`smoke.py` must run before the agent server: it writes `assets/vocabulary.json`,
and the agent builds its system prompt from that file. The prompt is built per
turn rather than at import, so a missing vocabulary is not a crash - the agent
answers by telling you which projects it does have a screenplay for, and
refuses to query until you pick one.

`adk api_server` reads `dailies_agent/` from the current directory, so run it
from the project root. Its first run on a machine asks (once) whether to
enable anonymous telemetry. It serves the same REST API `adk web` does
(sessions, `/run_sse`) but with no browser UI of its own - the UI is
`projects_api`'s `/app`, below, which is what you actually chat through.
`adk web`'s own developer chat still works if you want to poke the raw API,
but it is not the product surface any more.

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

    .venv/Scripts/adk.exe api_server
    .venv/Scripts/python.exe -m uvicorn projects_api:app --reload --port 8080

Open http://127.0.0.1:8080/onboard?token=YOUR_TOKEN (set `ONBOARD_TOKEN` in
`.env`; without it the wizard and create/upload/ingest routes return 404 —
see **Decisions and tradeoffs**). After clips are on disk (upload or Drive
sync), ingest from the wizard's button (or the CLI it shows as a fallback),
then open the dailies desk - `/app` - which the wizard links to already
scoped to that project.

`/app` is a purpose-built interface, not ADK's developer chat: a viewer next
to a camera-report select list, clip links that play inline, and an export
for the takes you circle. It proxies the agent over HTTP (`ADK_BASE_URL`,
default `http://127.0.0.1:8000` - what `adk api_server` listens on), so the
browser only ever talks to `projects_api` on :8080.

### Switching production mid-session

One agent process serves every production. `PROJECT_ID` in `.env` is only
the project a *new* session starts on; the session's own state wins over it.
`/app?project=<id>` seeds that state when the session opens, which is how the
wizard's link scopes a session with no typing. Asking in plain English still
works too, from `/app` or from `adk web`'s own chat if you're poking the API
directly:

    use project lailamajnu

That calls the agent's `set_active_project` tool, which stores the slug in
session state and rebuilds the prompt from that project's vocabulary on the
same turn - no restart, no `.env` edit. Ask "which projects do you have?" and
it lists every project whose screenplay has been parsed. A slug with no
parsed screenplay is refused rather than silently queried, because filtering
`project_id` on a project that logged nothing returns zero rows and looks
identical to an empty archive.

### Google Drive folder (ongoing dailies)

Do **not** use `gcloud auth application-default login` for Drive — Google
blocks the Cloud SDK app on that sensitive scope ("This app is blocked").
Service-account JSON keys are also blocked by org policy.

1. [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent?project=devpost-506321)
   → **External** → **Testing** (do not publish).
2. Add scope `https://www.googleapis.com/auth/drive.readonly`.
3. **Test users** → add the Google account that owns the dailies folder.
4. [Credentials](https://console.cloud.google.com/apis/credentials?project=devpost-506321)
   → **Create credentials** → **OAuth client ID** → type **Desktop app**
   (not the existing Web client). Download JSON as `client_secret.json`
   in the repo root (gitignored).
5. Add scope `https://www.googleapis.com/auth/drive` (See, edit, create,
   and delete all Google Drive files) — needed to create `Project1` folders.
6. Login / re-login (must allow edit, not view-only):

        .venv/Scripts/python.exe drive_sync.py login

   Then seed a movie folder under the parent dailies Drive folder:

        $env:DRIVE_DAILIES_FOLDER_ID="1nymloBR2S7nuELOyzbaYgi3Y3onOhxXY"
        .venv/Scripts/python.exe drive_sync.py bootstrap Project1

Keep `uvicorn projects_api` running — it polls every 2 minutes. Paste the
folder URL in `/onboard`. Or:

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
