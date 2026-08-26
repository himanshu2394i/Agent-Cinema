# Full deploy script for devpost-506321
# Run from project root in PowerShell after: gcloud auth login

$ErrorActionPreference = "Stop"
$Project = "devpost-506321"
$Region = "us-central1"
$Service = "dailies-agent"
$ProjectNumber = "688960954615"

Write-Host "==> Linking billing (skip if already linked)..."
gcloud billing projects link $Project --billing-account=0187B3-8B0A24-6CD50F 2>$null

Write-Host "==> Enabling APIs..."
gcloud services enable aiplatform.googleapis.com run.googleapis.com secretmanager.googleapis.com `
  artifactregistry.googleapis.com cloudbuild.googleapis.com --project=$Project

Write-Host "==> Granting Cloud Run build permissions..."
gcloud projects add-iam-policy-binding $Project `
  --member="serviceAccount:${ProjectNumber}-compute@developer.gserviceaccount.com" `
  --role="roles/storage.objectAdmin" --quiet
gcloud projects add-iam-policy-binding $Project `
  --member="serviceAccount:${ProjectNumber}@cloudbuild.gserviceaccount.com" `
  --role="roles/run.admin" --quiet
gcloud projects add-iam-policy-binding $Project `
  --member="serviceAccount:${ProjectNumber}@cloudbuild.gserviceaccount.com" `
  --role="roles/iam.serviceAccountUser" --quiet

Write-Host "==> Bundling agent dependencies..."
New-Item -ItemType Directory -Force -Path "dailies_agent\assets" | Out-Null
Copy-Item "assets\vocabulary.json" "dailies_agent\assets\vocabulary.json" -Force

Write-Host "==> Creating ClickHouse secret (skip if exists)..."
$pass = ((Get-Content ".env" | Where-Object { $_ -match '^CLICKHOUSE_PASSWORD=' }) -replace '^CLICKHOUSE_PASSWORD=','').Trim()
# Write to a temp file instead of piping: PowerShell adds a trailing newline
# to piped strings, which breaks ClickHouse auth when mounted as an env var.
$passFile = Join-Path $env:TEMP "clickhouse-password.bin"
[System.IO.File]::WriteAllText($passFile, $pass, (New-Object System.Text.UTF8Encoding $false))
try {
  gcloud secrets create clickhouse-password --data-file=$passFile --project=$Project --replication-policy=automatic 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "    Secret may already exist; updating version..."
    gcloud secrets versions add clickhouse-password --data-file=$passFile --project=$Project
  }
} finally {
  Remove-Item $passFile -Force -ErrorAction SilentlyContinue
}

Write-Host "==> Deploying to Cloud Run (5-10 min)..."
$env:ADK_DISABLE_TELEMETRY = "1"
.venv\Scripts\adk.exe deploy cloud_run `
  --project=$Project --region=$Region --service_name=$Service --with_ui `
  dailies_agent -- --allow-unauthenticated --quiet

Write-Host "==> Wiring env vars + secret..."
$chHost = ((Get-Content ".env" | Where-Object { $_ -match '^CLICKHOUSE_HOST=' }) -replace '^CLICKHOUSE_HOST=','').Trim()
gcloud run services update $Service --region=$Region --project=$Project `
  --set-env-vars="CLICKHOUSE_HOST=$chHost,CLICKHOUSE_PORT=8443,CLICKHOUSE_USER=default,CLICKHOUSE_SECURE=true,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$Project,GOOGLE_CLOUD_LOCATION=$Region,AGENT_MODEL=gemini-2.5-flash" `
  --set-secrets="CLICKHOUSE_PASSWORD=clickhouse-password:latest"

Write-Host "==> Granting Vertex AI to Cloud Run service account..."
gcloud projects add-iam-policy-binding $Project `
  --member="serviceAccount:${ProjectNumber}-compute@developer.gserviceaccount.com" `
  --role="roles/aiplatform.user" --quiet

$url = gcloud run services describe $Service --region=$Region --project=$Project --format="value(status.url)"
Write-Host ""
Write-Host "Deployed: $url"
Write-Host "Test: Which clips show Ben indoors?"
