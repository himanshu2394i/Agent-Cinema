"""End-to-end smoke test: screenplay -> vocabulary -> clip -> validated rows.

    python smoke.py assets/notld_1968_screenplay.pdf assets/sintel_trailer.mp4
    python smoke.py assets/notld_1968_screenplay.pdf assets/clips/A001_C0001.mp4 --project notld_1968

This is the whole ingest half in one run, ending with the shots inserted into
ClickHouse so the agent can answer questions about the clip. Re-running
replaces that clip's rows rather than duplicating them.

The parsed vocabulary is cached, because re-reading a 120-page screenplay on
every run burns quota for no new information. Delete the cache to re-parse.
"""

import dataclasses
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from db import connect, replace_clip
from ingest import log_clip
from ingest import upload as _upload
from parse_script import parse_screenplay
from vocab import VOCABULARY_CACHE, ProjectVocabulary, load_vocabulary

CACHE = VOCABULARY_CACHE


def parse_args(argv: list[str]) -> tuple[Path, Path, str] | None:
    """Return (pdf, video, project_id) or None if usage is wrong."""
    args = list(argv)
    project_id = "notld_1968"
    if "--project" in args:
        idx = args.index("--project")
        if idx + 1 >= len(args):
            return None
        project_id = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
    if len(args) != 2:
        return None
    return Path(args[0]), Path(args[1]), project_id


def vocabulary_for(pdf: Path, client, project_id: str = "notld_1968") -> ProjectVocabulary:
    # Prefer a per-project cache when present; fall back to the legacy path.
    try:
        cached = load_vocabulary(project_id=project_id)
        print(f"vocabulary: cached (project {project_id})")
        return cached
    except FileNotFoundError:
        pass

    if project_id == "notld_1968" and CACHE.exists():
        print(f"vocabulary: cached ({CACHE})")
        return load_vocabulary(CACHE)

    print(f"vocabulary: parsing {pdf.name} ...")
    start = time.perf_counter()
    result = parse_screenplay(pdf.read_bytes(), client)
    print(f"  parsed in {time.perf_counter() - start:.0f}s")
    CACHE.write_text(json.dumps(dataclasses.asdict(result), indent=2))
    return result


def upload(video: Path, client):
    print(f"upload: {video.name} ({video.stat().st_size / 1e6:.1f} MB) ...")
    uri = _upload(video, client)
    print(f"  ready: {uri}")
    return uri


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv if argv is not None else sys.argv[1:])
    if parsed is None:
        print(__doc__)
        return 2

    pdf, video, project_id = parsed
    load_dotenv()
    client = genai.Client()

    vocabulary = vocabulary_for(pdf, client, project_id=project_id)
    for name in ("characters", "locations", "props", "scenes"):
        values = getattr(vocabulary, name)
        print(f"  {name:11} {len(values):4}  {', '.join(values[:6])}")

    uri = upload(video, client)

    print(f"logging shots (project_id={project_id}) ...")
    start = time.perf_counter()
    rows = log_clip(
        uri, vocabulary, client, source_file=video.name, project_id=project_id
    )
    print(f"  {len(rows)} shots in {time.perf_counter() - start:.0f}s\n")

    written = replace_clip(connect(), rows)
    print(f"inserted {written} shots into ClickHouse")
    print()

    for row in rows:
        span = f"{row['start_seconds']:>6.1f}-{row['end_seconds']:<6.1f}"
        print(f"{span} {row['shot_size']:<17} {row['camera_movement']:<9} "
              f"{row['int_ext']:<10} {row['time_of_day']:<14} "
              f"{','.join(row['characters']) or '-'}")
        print(f"       {row['action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
