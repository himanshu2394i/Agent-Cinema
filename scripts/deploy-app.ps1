# Deploy the real product UI (projects_api.py, GET /app) to Cloud Run.
# Stages projects_api.py + the modules it actually imports into deploy/app
# for the build. Run from project root, after dailies-agent and
# dailies-clips are already deployed (this script looks up their URLs).
#
# What will NOT work in this deployment (read before you rely on it):
#
# 1. POST /projects/{id}/ingest (and its GET status poll) needs ClickHouse
#    (CLICKHOUSE_HOST/PORT/USER/PASSWORD) and a Gemini client to actually
#    log shots - neither is wired here, and db.py/ingest_all.py are not
#    staged into the image, so the route fails with an import error rather
#    than a silent no-op. A 171-clip batch run also does not belong behind
#    a Cloud Run request's BackgroundTasks: the instance can scale to zero
#    or recycle mid-batch. Run ingest_all.py from a machine you control
#    instead. Not fixed here on purpose - see the task notes.
# 2. POST /projects/{id}/clips (manual clip upload) writes to this
#    container's local disk, which is ephemeral (wiped on restart/scale-to-
#    zero) and never read by dailies-clips (which serves from its own image
#    or GCS). An uploaded clip will not persist or become watchable.
# 3. Google Drive sync (the background poll loop and POST
#    /projects/{id}/drive/sync) silently no-ops unless a Drive credential
#    is provisioned - this script does not create one, matching .env
#    (which has no GOOGLE_DRIVE_CREDENTIALS today). To enable it later,
#    store a service-account JSON in Secret Manager and mount it with
#    --set-secrets, the same way this script's CLICKHOUSE-less sibling
#    deploy.ps1 mounts clickhouse-password.
# 4. /config and /trace import the dailies_agent package for
#    DEFAULT_PROJECT_ID and the evidence-ledger renderer, and that
#    package's __init__.py unconditionally imports agent.py - which pulls
#    in the whole google-adk dependency tree even though this service
#    never runs the agent itself (it only calls the already-deployed
#    dailies-agent over HTTP via ADK_BASE_URL). Unavoidable without editing
#    projects_api.py/dailies_agent, which is out of scope here.

$ErrorActionPreference = "Stop"
$Project = "devpost-506321"
$Region = "us-central1"
$Service = "dailies-app"
$Root = Split-Path -Parent $PSScriptRoot
$Stage = Join-Path $Root "deploy\app"

Write-Host "==> Staging app build context..."
Remove-Item -Recurse -Force (Join-Path $Stage "static") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Stage "dailies_agent") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Stage "assets") -ErrorAction SilentlyContinue

# Root modules projects_api.py imports directly.
Copy-Item (Join-Path $Root "projects_api.py") (Join-Path $Stage "projects_api.py") -Force
Copy-Item (Join-Path $Root "projects.py") (Join-Path $Stage "projects.py") -Force
Copy-Item (Join-Path $Root "drive_sync.py") (Join-Path $Stage "drive_sync.py") -Force
Copy-Item (Join-Path $Root "parse_script.py") (Join-Path $Stage "parse_script.py") -Force
Copy-Item (Join-Path $Root "vocab.py") (Join-Path $Stage "vocab.py") -Force

# GET /onboard and GET /app.
Copy-Item (Join-Path $Root "static") (Join-Path $Stage "static") -Recurse -Force

# GET /config and GET /trace lazily import dailies_agent.agent /
# dailies_agent.investigation. Copy the whole package (its modules import
# each other) but skip the local dev session db and caches.
Copy-Item (Join-Path $Root "dailies_agent") (Join-Path $Stage "dailies_agent") -Recurse -Force
Remove-Item -Recurse -Force (Join-Path $Stage "dailies_agent\.adk") -ErrorAction SilentlyContinue
Get-ChildItem (Join-Path $Stage "dailies_agent") -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Project manifests + vocabularies only - never the .mp4 clips (2.5GB+;
# those are served by dailies-clips/GCS, not this service).
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "assets") | Out-Null
$legacyVocab = Join-Path $Root "assets\vocabulary.json"
if (Test-Path $legacyVocab) {
    Copy-Item $legacyVocab (Join-Path $Stage "assets\vocabulary.json") -Force
}
$projectsRoot = Join-Path $Root "assets\projects"
if (Test-Path $projectsRoot) {
    Get-ChildItem $projectsRoot -Directory | ForEach-Object {
        $srcDir = $_.FullName
        $dstDir = Join-Path $Stage "assets\projects\$($_.Name)"
        New-Item -ItemType Directory -Force -Path (Join-Path $dstDir "clips") | Out-Null
        foreach ($name in @("manifest.json", "vocabulary.json", "screenplay.pdf")) {
            $src = Join-Path $srcDir $name
            if (Test-Path $src) {
                Copy-Item $src (Join-Path $dstDir $name) -Force
            }
        }
    }
}
$stagedProjects = (Get-ChildItem (Join-Path $Stage "assets\projects") -Directory -ErrorAction SilentlyContinue).Count
Write-Host "    Staged $stagedProjects project manifest(s), no clips"

Write-Host "==> Looking up sibling service URLs..."
$adkBase = gcloud run services describe dailies-agent --region=$Region --project=$Project --format="value(status.url)"
if (-not $adkBase) { throw "dailies-agent URL missing - deploy it first (scripts/deploy.ps1)" }
$clipBase = gcloud run services describe dailies-clips --region=$Region --project=$Project --format="value(status.url)"
if (-not $clipBase) { throw "dailies-clips URL missing - deploy it first (scripts/deploy-clips.ps1)" }
Write-Host "    ADK_BASE_URL=$adkBase"
Write-Host "    CLIP_BASE_URL=$clipBase"

Write-Host "==> Deploying $Service to Cloud Run..."
# --timeout=300: /projects/{id}/ask relays the agent's run_sse call with a
# 120s upstream timeout; give the request room instead of Cloud Run's 60s
# default cutting it off first.
# GCS_INGEST_BUCKET: lets /projects count clips that live only in GCS (this
# image ships none). Read access comes from the storage.objectViewer binding
# scripts/deploy-clips.ps1 already granted the compute service account on
# this bucket - no new IAM grant needed here.
gcloud run deploy $Service `
  --project=$Project `
  --region=$Region `
  --source=$Stage `
  --allow-unauthenticated `
  --memory=1Gi `
  --cpu=1 `
  --min-instances=0 `
  --max-instances=3 `
  --timeout=300 `
  --set-env-vars="ADK_BASE_URL=$adkBase,CLIP_BASE_URL=$clipBase,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$Project,GOOGLE_CLOUD_LOCATION=$Region,GCS_INGEST_BUCKET=dailies-ingest-devpost-506321" `
  --quiet

Write-Host "==> Granting Vertex AI to Cloud Run service account (no-op if scripts/deploy.ps1 already did)..."
$ProjectNumber = gcloud projects describe $Project --format="value(projectNumber)"
gcloud projects add-iam-policy-binding $Project `
  --member="serviceAccount:${ProjectNumber}-compute@developer.gserviceaccount.com" `
  --role="roles/aiplatform.user" --quiet

$url = gcloud run services describe $Service --region=$Region --project=$Project --format="value(status.url)"
Write-Host ""
Write-Host "Deployed: $url"
Write-Host "Smoke: ${url}/app"
