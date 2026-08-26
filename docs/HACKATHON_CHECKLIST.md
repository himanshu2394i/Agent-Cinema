# Agentic Cinema — Hackathon Checklist

Use this in order. Check items off as you go.

## Credits and accounts

- [ ] **ClickHouse Cloud** — create service; claim ~$400 hackathon credits from the [hackathon page](https://devpost.com) ClickHouse partner link
- [ ] **Google Cloud** — apply hackathon GCP credits to your project; confirm billing is linked
- [ ] **Enable APIs** — `aiplatform.googleapis.com` (Vertex), optionally Cloud Run / Secret Manager
- [ ] **Rotate secrets** — if any key/password was ever pasted in chat, reset it in ClickHouse + AI Studio

## Data (one-time local setup)

- [ ] Download NOTLD screenplay + film (commands in `README.md`)
- [ ] `clips.py` → 20 clips in `assets/clips/`
- [ ] `db.py init` → create `shots` table
- [ ] `smoke.py` → parse screenplay, cache `assets/vocabulary.json`, log one clip
- [ ] `ingest_all.py assets/clips` → all 20 clips logged (~177 shot rows)
- [ ] Optional: `db.py load 2000000` → synthetic archive for scale demo

## Vertex AI (you have GCP credits — do this)

- [ ] Set `.env` per `docs/DEPLOY.md` (`GOOGLE_GENAI_USE_VERTEXAI`, project, location)
- [ ] Probe models; pick one that returns OK (not just listed)
- [ ] Re-run `smoke.py` on Vertex to confirm parse + ingest work
- [ ] Remove / unset `GOOGLE_API_KEY` so nothing falls back to AI Studio

## Guardrails (from ClickHouse build session)

- [ ] Create `agent_readonly` ClickHouse user (SQL in `docs/DEPLOY.md`)
- [ ] Agent deploy uses read-only user; ingest scripts use write-capable user locally
- [ ] Confirm agent prompt includes query `SETTINGS` limits (in `shot_schema.py`)
- [ ] Confirm `CLICKHOUSE_ALLOW_WRITE_ACCESS=false` on MCP subprocess

## Deploy

- [ ] `adk deploy cloud_run --with_ui dailies_agent` (full steps in `docs/DEPLOY.md`)
- [ ] ClickHouse password in Secret Manager, not plain env
- [ ] Copy deployed **HTTPS URL** for Devpost
- [ ] Test: *"Which clips show Ben indoors?"* on live URL
- [ ] Test negative: *"Which clips show someone riding a horse?"* — agent explains search, not bare "no"

## Tests and repo hygiene

- [ ] `.venv/Scripts/python.exe -m pytest -q` — all green
- [ ] `git status` clean (or only intentional changes)
- [ ] No `.env`, `.mp4`, or `.pdf` tracked in git

## Demo video (~2 min)

Follow `docs/SUBMISSION.md` script:

1. [ ] Problem — folder of identical clip names
2. [ ] Screenplay → vocabulary (`smoke.py`)
3. [ ] Logging — shots streaming out; optional Judy `unknown` row
4. [ ] Payoff — 2–3 agent questions (record separately, cut waiting)
5. [ ] Scale — `db.py demo` (177 real + 2M synthetic, say which is which)

**Before recording:** check Gemini quota; use a model you have not burned today.

## Devpost submission

- [ ] **Title** — Dailies Triage (or your choice)
- [ ] **Elevator pitch** — assistant editor that logs footage and answers shot questions in plain English
- [ ] **Built with** — `google-gemini`, `google-adk`, `vertex-ai`, `clickhouse`, `mcp`, `cloud-run`, `python`
- [ ] **Try it** — deployed Cloud Run URL
- [ ] **Video** — uploaded and linked
- [ ] **Inspiration / What it does / How we built it** — copy/adapt from `docs/SUBMISSION.md`
- [ ] **Challenges** — vocabulary drift, ClickHouse dedup, empty-result protocol, Judy row, survey threshold, batch retry quota burn
- [ ] **What's next** — real dailies for continuity, survey at documentary scale

## Judging alignment (ClickHouse session)

- [ ] Gemini + Google ADK agent — yes
- [ ] ClickHouse at **runtime via MCP** — yes (`mcp-clickhouse`)
- [ ] Fast SQL retrieval, not vector search — yes; cite `db.py demo` latencies
- [ ] Entertainment / media use case — yes (dailies logging)
- [ ] Optional bonus: mention read-only user + query timeouts if judges ask about safety

## Day-of submission sanity check

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe db.py demo
# open deployed URL, one agent question
git ls-files | grep -E '\.env$|\.pdf|\.mp4'   # should print nothing
```
