"""Per-production project directories and manifests.

Each movie/documentary gets its own folder under assets/projects/{id}/ with
a manifest, vocabulary cache, and clip uploads. The agent and ingest pipeline
scope ClickHouse rows by the same project_id.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path("assets/projects")
LEGACY_CLIPS_DIR = Path("assets/clips")
DEFAULT_CLIP_BASE_URL = "http://127.0.0.1:8080"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CLIP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.mp4$", re.IGNORECASE)


def _validate_slug(project_id: str) -> None:
    if not SLUG_RE.match(project_id):
        raise ValueError(
            f"project_id {project_id!r} is not a valid slug "
            "(use lowercase letters, digits, hyphens, underscores)"
        )


def _safe_clip_name(filename: str) -> str:
    """Basename-only .mp4; rejects path traversal and odd names."""
    normalized = filename.replace("\\", "/")
    if "/" in normalized or normalized != Path(filename).name or ".." in normalized:
        raise ValueError(f"clip filename {filename!r} is not allowed")
    name = Path(filename).name
    if not CLIP_NAME_RE.match(name):
        raise ValueError(f"clip filename {filename!r} is not a safe .mp4 name")
    return name


def project_dir(project_id: str) -> Path:
    _validate_slug(project_id)
    return PROJECTS_ROOT / project_id


def vocabulary_path(project_id: str) -> Path:
    return project_dir(project_id) / "vocabulary.json"


def clips_dir(project_id: str) -> Path:
    return project_dir(project_id) / "clips"


def resolve_clip(project_id: str, filename: str) -> Path | None:
    """Locate a clip on disk for a project, with legacy assets/clips fallback."""
    _validate_slug(project_id)
    name = _safe_clip_name(filename)
    candidates = [clips_dir(project_id) / name]
    if project_id == "notld_1968":
        candidates.append(LEGACY_CLIPS_DIR / name)
    for path in candidates:
        if path.is_file():
            return path
    return None


def clip_watch_url(
    filename: str,
    project_id: str = "notld_1968",
    base_url: str = DEFAULT_CLIP_BASE_URL,
) -> str:
    """URL the agent cites so an editor can open the HTML5 clip viewer."""
    name = _safe_clip_name(filename)
    base = base_url.rstrip("/")
    return f"{base}/watch?project={project_id}&file={name}"


def create_project(project_id: str, name: str) -> Path:
    """Create a new project directory with manifest and clips folder."""
    _validate_slug(project_id)
    root = project_dir(project_id)
    if root.exists():
        raise FileExistsError(f"project {project_id!r} already exists")
    (root / "clips").mkdir(parents=True)
    manifest = {
        "id": project_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return root


def list_projects() -> list[dict]:
    """Return manifests for every project on disk, oldest first."""
    if not PROJECTS_ROOT.exists():
        return []
    out: list[dict] = []
    for path in sorted(PROJECTS_ROOT.iterdir()):
        if not path.is_dir():
            continue
        manifest_file = path / "manifest.json"
        if manifest_file.exists():
            out.append(json.loads(manifest_file.read_text()))
    return out
