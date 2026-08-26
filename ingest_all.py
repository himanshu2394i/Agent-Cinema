"""Ingest a directory of clips into ClickHouse.

    python ingest_all.py assets/clips
    python ingest_all.py assets/clips --force

One clip at a time, on purpose. A failure mid-batch leaves everything already
logged in place, and re-running is cheap: clips already logged in ClickHouse
are skipped, so a retry only spends an API call on the clips still missing.
Pass --force to re-ingest everything anyway, e.g. after changing the logging
prompt and wanting fresh results for clips that already succeeded.
"""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from db import connect, logged_sources, replace_clip
from ingest import log_clip, upload
from vocab import load_vocabulary


def upload_and_log(video: Path, vocabulary, client, project_id: str) -> list[dict]:
    """The real per-clip pipeline: upload to the Files API, then log_clip."""
    return log_clip(
        upload(video, client), vocabulary, client,
        source_file=video.name, project_id=project_id,
    )


def run_batch(videos, vocabulary, client, db, log_clip, replace_clip, logged_sources,
              force=False, project_id="notld_1968", log=print) -> tuple[int, list[str], list[str]]:
    """Log every clip in `videos`, one at a time.

    A clip whose name is already logged in ClickHouse is skipped, not
    re-ingested - re-running a batch after a partial failure must not spend
    an API call on clips it already has. `force=True` bypasses the skip, for
    when the logging prompt changed and fresh results are wanted deliberately.

    A clip that raises is recorded as failed and the batch continues - a
    stuck or rate-limited clip should not cost the rest of the run. Returns
    (total shots written, names of clips that failed, names of clips skipped).
    """
    total = 0
    failed: list[str] = []
    skipped: list[str] = []
    already_logged = set() if force else logged_sources(db)
    for index, video in enumerate(videos, start=1):
        if video.name in already_logged:
            log(f"[{index}/{len(videos)}] {video.name} - already logged, skipping")
            skipped.append(video.name)
            continue
        log(f"[{index}/{len(videos)}] {video.name}")
        try:
            start = time.perf_counter()
            rows = log_clip(video, vocabulary, client)
            written = replace_clip(db, rows)
            total += written
            log(f"    {written} shots in {time.perf_counter() - start:.0f}s")
        except Exception as error:
            log(f"    FAILED: {type(error).__name__}: {error}")
            failed.append(video.name)
    return total, failed, skipped


def exit_code(failed: list[str]) -> int:
    return 1 if failed else 0


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    project_id = "notld_1968"
    if "--project" in args:
        idx = args.index("--project")
        project_id = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
    paths = [a for a in args if a not in ("--force",)]
    if len(paths) != 1:
        print(__doc__)
        return 2

    load_dotenv()
    client = genai.Client()
    db = connect()
    vocabulary = load_vocabulary(project_id=project_id)

    videos = sorted(Path(paths[0]).glob("*.mp4"))
    if not videos:
        print(f"no .mp4 files in {paths[0]}")
        return 1

    total, failed, skipped = run_batch(
        videos, vocabulary, client, db,
        log_clip=lambda v, voc, cli: upload_and_log(v, voc, cli, project_id),
        replace_clip=replace_clip,
        logged_sources=logged_sources, force=force, project_id=project_id,
    )

    ingested = len(videos) - len(failed) - len(skipped)
    print(f"\n{total} shots from {ingested}/{len(videos)} clips"
          + (f" ({len(skipped)} already logged, skipped)" if skipped else ""))
    if failed:
        print("failed: " + ", ".join(failed))
        print("re-run to retry - already-logged clips are skipped, so it only costs "
              "one API call per clip still missing")
    return exit_code(failed)


if __name__ == "__main__":
    raise SystemExit(main())
