# Slim public clip watcher for CLIP_BASE_URL (hackathon demo).
# Build context is staged by scripts/deploy-clips.ps1 (includes mp4s).
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.115.12 uvicorn[standard]==0.34.2

COPY projects.py watch_server.py ./
COPY assets/clips ./assets/clips

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "watch_server:app", "--host", "0.0.0.0", "--port", "8080"]
