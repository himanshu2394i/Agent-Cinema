# Cloud Run image for projects_api.py - the real product UI (GET /app),
# replacing ADK's generic developer chat UI on the public demo.
#
# Build context is staged by scripts/deploy-app.ps1 (no .mp4 clips - those
# are served by dailies-clips/GCS). See that script's header for what does
# and does not work in this deployment.
FROM python:3.12-slim

WORKDIR /app

# Pinned to the versions in the local venv (.venv/Scripts/python.exe -m pip
# freeze). google-adk pulls in a large dependency tree on its own - that is
# unavoidable, projects_api.py's /config and /trace routes import the
# dailies_agent package, whose __init__.py always imports agent.py.
# No clickhouse-connect / mcp-clickhouse: nothing this service imports at
# module load needs them (see script header, point 1).
RUN pip install --no-cache-dir \
    fastapi==0.141.1 \
    "uvicorn[standard]==0.52.4" \
    python-multipart==0.0.32 \
    python-dotenv==1.2.3 \
    pydantic==2.13.4 \
    google-genai==2.19.0 \
    google-adk==2.7.1 \
    mcp==1.29.0 \
    google-api-python-client==2.199.0 \
    google-auth==2.56.3 \
    google-auth-httplib2==0.4.2 \
    google-auth-oauthlib==1.4.1

COPY projects_api.py projects.py drive_sync.py parse_script.py vocab.py ./
COPY static ./static
COPY dailies_agent ./dailies_agent
COPY assets ./assets

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "projects_api:app", "--host", "0.0.0.0", "--port", "8080"]
