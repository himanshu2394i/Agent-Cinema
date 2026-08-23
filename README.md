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
| `synth.py` | Synthetic dailies, for testing search at archive scale |
| `db.py` | ClickHouse connection, schema, bulk load |
| `dailies_agent/` | The ADK agent (queries ClickHouse over MCP) |
| `smoke.py` | Whole pipeline in one run: screenplay -> vocabulary -> clip -> ClickHouse |

## Running it

Prerequisites: Python 3.12, a Google Cloud / Gemini API credential, a
ClickHouse Cloud service, and (only for `clips.py`) `ffmpeg`/`ffprobe` on
your PATH.

    python -m venv .venv
    .venv/Scripts/python.exe -m pip install -r requirements.txt
    cp .env.example .env    # then fill in your Gemini and ClickHouse Cloud values

    .venv/Scripts/python.exe db.py init
    .venv/Scripts/python.exe smoke.py assets/notld_1968_screenplay.pdf assets/sintel_trailer.mp4
    .venv/Scripts/adk.exe web

`adk web` reads `dailies_agent/` from the current directory, so run it from
the project root. Its first run on a machine asks (once) whether to enable
anonymous telemetry. Once it's up, open http://127.0.0.1:8000 and ask it a
question about the footage you just logged.

To ingest more than one clip at a time, cut a feature into stand-in dailies
and batch-ingest the directory:

    .venv/Scripts/python.exe clips.py assets/notld_full.mp4 assets/clips 20 45
    .venv/Scripts/python.exe ingest_all.py assets/clips

## Tests

    .venv/Scripts/python.exe -m pytest -q

60 tests pass. Every Gemini and ClickHouse call in the test suite goes
through a hand-written fake client, not the real SDKs, so the whole pipeline
is testable without a key or a live database.

## Credits

Test assets are *Night of the Living Dead* (1968), public domain.
