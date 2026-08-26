# Deploying Dailies Triage

This guide covers moving from local `adk web` to **Vertex AI + Cloud Run**,
with the guardrails Zoe/Andre recommended in the ClickHouse build session.

## Prerequisites

- Google Cloud project with billing enabled and hackathon credits applied
- `gcloud` CLI installed and authenticated
- ClickHouse Cloud service (claim ~$400 credits from the hackathon page)
- Python venv with `requirements.txt` installed locally

## 1. Vertex AI

Link billing and enable the API:

```bash
gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
```

Probe which Gemini models your project can actually call (listing ≠ available):

```bash
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID GOOGLE_CLOUD_LOCATION=us-central1 \
  .venv/Scripts/python.exe -c "
from google import genai
for m in ['gemini-3.6-flash', 'gemini-2.5-flash', 'gemini-3.1-pro-preview']:
    try:
        genai.Client().models.generate_content(model=m, contents='ok')
        print(m, 'OK')
    except Exception as e:
        print(m, type(e).__name__, str(e)[:80])
"
```

Set `.env` (and later Cloud Run env vars):

```
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=us-central1
AGENT_MODEL=<model that returned OK>
```

Do **not** set `GOOGLE_API_KEY` on Cloud Run — it can silently fall back to
the metered AI Studio path.

## 2. ClickHouse guardrails

### Read-only MCP (already enforced in code)

`dailies_agent/agent.py` passes `CLICKHOUSE_ALLOW_WRITE_ACCESS=false` to
`mcp-clickhouse`. The agent prompt also instructs SELECT-only queries with
`SETTINGS max_execution_time`, `max_result_rows`, and `max_rows_to_read`.

### Read-only database user (recommended)

Create a dedicated user for the deployed agent in ClickHouse Cloud SQL console:

```sql
CREATE USER IF NOT EXISTS agent_readonly
  IDENTIFIED BY 'choose-a-strong-password'
  SETTINGS readonly = 1,
           max_execution_time = 30,
           max_result_rows = 1000,
           max_rows_to_read = 10000000;

GRANT SELECT ON default.shots TO agent_readonly;
```

Use `agent_readonly` in `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` for the
agent. Keep `default` (or a write-capable user) only for `ingest_all.py` and
`smoke.py` on your machine.

### ClickHouse Cloud managed MCP (optional, local dev only)

The hackathon allows either the open-source `mcp-clickhouse` server **or**
ClickHouse Cloud's hosted MCP at `https://mcp.clickhouse.cloud/mcp` (OAuth).
This project uses the open-source server because Cloud Run cannot complete an
OAuth browser flow headlessly. Zoe confirmed both are valid for submission.

## 3. Cloud Storage for ingest (optional, saves upload time)

```bash
gcloud storage buckets create gs://YOUR_PROJECT_ID-dailies --location=us-central1
gcloud storage cp assets/clips/*.mp4 gs://YOUR_PROJECT_ID-dailies/clips/
```

`ingest.log_clip` already accepts `gs://` URIs when running ingest on Vertex.

## 4. Deploy the agent to Cloud Run

For project `devpost-506321`, the one-shot script deploys the agent **and** a
public clip watcher (`dailies-clips`) so agent answers can cite working
`/watch` links via `CLIP_BASE_URL`:

```powershell
.\scripts\deploy.ps1
```

Or step by step — first the public clip service (bundles local `assets/clips/`
into the image; those mp4s are gitignored and must exist on the deploy machine):

```powershell
.\scripts\deploy-clips.ps1
# prints CLIP_BASE_URL=https://dailies-clips-....run.app
```

Then the agent:

```bash
gcloud config set project YOUR_PROJECT_ID

.venv/Scripts/adk.exe deploy cloud_run \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  --service_name=dailies-agent \
  --with_ui \
  dailies_agent
```

Store the ClickHouse password in Secret Manager (never in shell history).
On Windows, write to a temp file — **do not pipe** from PowerShell or a
trailing newline gets stored and ClickHouse returns error 194:

```powershell
$pass = (Get-Content .env | Where-Object { $_ -match '^CLICKHOUSE_PASSWORD=' }) -replace '^CLICKHOUSE_PASSWORD=',''
$passFile = New-TemporaryFile
Set-Content -Path $passFile -Value $pass -NoNewline
gcloud secrets create clickhouse-password --data-file=$passFile --project=YOUR_PROJECT_ID
Remove-Item $passFile
```

```bash
gcloud run services update dailies-agent --region=us-central1 \
  --set-env-vars=CLICKHOUSE_HOST=YOUR_HOST.clickhouse.cloud,CLICKHOUSE_PORT=8443,CLICKHOUSE_USER=agent_readonly,CLICKHOUSE_SECURE=true,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1,AGENT_MODEL=gemini-2.5-flash,CLIP_BASE_URL=https://dailies-clips-XXXX.a.run.app \
  --set-secrets=CLICKHOUSE_PASSWORD=clickhouse-password:latest
```

`CLIP_BASE_URL` must be a **public** HTTPS base (not localhost). The
`dailies-clips` service serves `/watch?project=…&file=…` with HTML5 video.
Local onboarding still uses `projects_api` on port 8080.

**Do not use `GOOGLE_CLOUD_LOCATION=global`** for this agent. The global
endpoint has a separate, tighter RPM quota
(`GlobalGenerateContentRequestsPerMinutePerProjectPerBaseModel`) and is what
caused `429 RESOURCE_EXHAUSTED` on the live deploy. Use a regional location
that matches Cloud Run (`us-central1`).

Before picking a model, probe which ones your project can call in that region
(listing ≠ available — `gemini-2.0-flash` returned 404 in us-central1):

```bash
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID GOOGLE_CLOUD_LOCATION=us-central1 \
  .venv/Scripts/python.exe -c "
from google import genai
for m in ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash-002']:
    try:
        genai.Client().models.generate_content(model=m, contents='ok')
        print(m, 'OK')
    except Exception as e:
        print(m, type(e).__name__, str(e)[:80])
"
```

Get the URL:

```bash
gcloud run services describe dailies-agent --region=us-central1 --format="value(status.url)"
```

Wake ClickHouse Cloud if idle (services sleep after ~15 minutes of inactivity).

### Troubleshooting `429 RESOURCE_EXHAUSTED` (Vertex only)

Symptoms: chat fails after several tool calls; logs show
`429 RESOURCE_EXHAUSTED` from `google_llm.py` with backend `VERTEX_AI`.

**Root causes seen on this project:**

1. **`GOOGLE_CLOUD_LOCATION=global`** — hits the global RPM quota after a few
   rapid agent turns (each tool retry is another Gemini call). Fix: set
   `GOOGLE_CLOUD_LOCATION=us-central1` to match Cloud Run.
2. **Agent tool loop burning RPM** — failed ClickHouse queries (e.g. `SETTINGS`
   on a read-only user) cause extra Gemini round-trips before the real answer.
   The agent prompt now uses `LIMIT` instead of `SETTINGS`.
3. **Oversized tool results** — a query without `LIMIT` returned 152k rows,
   blowing the 1M input-token cap (`400 INVALID_ARGUMENT`, looks like a hang).
   Always cap with `LIMIT 1000` in agent SQL.

**Fix checklist (stay on Vertex — do not set `GOOGLE_API_KEY`):**

```bash
gcloud run services update dailies-agent --region=us-central1 --project=YOUR_PROJECT_ID \
  --update-env-vars=GOOGLE_CLOUD_LOCATION=us-central1,AGENT_MODEL=gemini-2.5-flash
```

The agent also sets ADK retry config (`HttpRetryOptions`, 5 attempts, 2–30s
backoff) for transient 429s. If 429 persists after the location fix, wait a
minute and retry — you may have hit a per-minute cap from a demo run.

## 5. Verify

```bash
.venv/Scripts/python.exe -m pytest -q
```

Ask the deployed agent: *"Which clips show Ben indoors?"*

If MCP fails, check logs:

```bash
gcloud run services logs read dailies-agent --region=us-central1 --limit=50
```

## 6. Before you submit

Live deployment (devpost-506321):

**Agent:** https://dailies-agent-hdu4hzk2uq-uc.a.run.app  
**Clip watch (`CLIP_BASE_URL`):** https://dailies-clips-hdu4hzk2uq-uc.a.run.app

Ask: *"List one clip where Ben appears indoors"* — answers should include a
markdown `/watch` link on the clips service.

- [ ] Deployed URL works with a real question
- [ ] Agent uses read-only ClickHouse credentials
- [ ] No `.env`, keys, or passwords in git (`git ls-files | grep -E '\.env$'`)
- [ ] Demo video recorded (see `docs/SUBMISSION.md`)
- [ ] Devpost form lists: `google-gemini`, `google-adk`, `vertex-ai`, `clickhouse`, `mcp`, `cloud-run`, `python`
