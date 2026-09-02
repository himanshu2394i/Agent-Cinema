# Deploy public HTML5 clip watcher to Cloud Run (CLIP_BASE_URL target).
# Stages local assets/clips (gitignored) into deploy/clips for the build.
# Only the 20 NOTLD clips ship in the image; every other project's clips
# (e.g. lailamajnu) are served by watch_server.py falling back to GCS, so
# this script also points the service at the bucket and grants it read
# access. Run from project root.

$ErrorActionPreference = "Stop"
$Project = "devpost-506321"
$Region = "us-central1"
$Service = "dailies-clips"
$Bucket = "dailies-ingest-devpost-506321"
$Root = Split-Path -Parent $PSScriptRoot
$Stage = Join-Path $Root "deploy\clips"

if (-not (Test-Path (Join-Path $Root "assets\clips\A001_C0001.mp4"))) {
  throw "assets/clips/*.mp4 missing - cut clips locally before deploying watch service"
}

Write-Host "==> Staging clip watch build context..."
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "assets\clips") | Out-Null
Copy-Item (Join-Path $Root "projects.py") (Join-Path $Stage "projects.py") -Force
Copy-Item (Join-Path $Root "watch_server.py") (Join-Path $Stage "watch_server.py") -Force
Copy-Item (Join-Path $Root "assets\clips\*.mp4") (Join-Path $Stage "assets\clips") -Force

$clipCount = (Get-ChildItem (Join-Path $Stage "assets\clips\*.mp4")).Count
Write-Host "    Staged $clipCount clips"

Write-Host "==> Deploying $Service to Cloud Run..."
gcloud run deploy $Service `
  --project=$Project `
  --region=$Region `
  --source=$Stage `
  --allow-unauthenticated `
  --memory=512Mi `
  --cpu=1 `
  --min-instances=0 `
  --max-instances=3 `
  --timeout=60 `
  --set-env-vars="GCS_INGEST_BUCKET=$Bucket" `
  --quiet

Write-Host "==> Granting the service's runtime account read access to gs://$Bucket ..."
$runtimeSa = gcloud run services describe $Service --region=$Region --project=$Project --format="value(spec.template.spec.serviceAccountName)"
if (-not $runtimeSa) {
  # No custom runtime SA set -> Cloud Run uses the project's default compute SA.
  $projectNumber = gcloud projects describe $Project --format="value(projectNumber)"
  $runtimeSa = "$projectNumber-compute@developer.gserviceaccount.com"
}
gcloud storage buckets add-iam-policy-binding "gs://$Bucket" `
  --member="serviceAccount:$runtimeSa" `
  --role="roles/storage.objectViewer" `
  --project=$Project `
  --quiet
Write-Host "    Granted roles/storage.objectViewer on gs://$Bucket to $runtimeSa"

$url = gcloud run services describe $Service --region=$Region --project=$Project --format="value(status.url)"
Write-Host ""
Write-Host "CLIP_BASE_URL=$url"
$smoke = "${url}/watch?project=notld_1968&file=A001_C0007.mp4"
Write-Host "Smoke (in-image clip): $smoke"
$smokeGcs = "${url}/watch?project=lailamajnu&file=A001_C0001.mp4"
Write-Host "Smoke (GCS fallback):  $smokeGcs"
