"""Ingest a directory of clips into ClickHouse.

    python ingest_all.py assets/clips

One clip at a time, on purpose. A failure mid-batch leaves everything already
logged in place, and re-running is always safe - replace_clip makes each clip
idempotent, so the right move after any failure is to run it again.
"""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from db import connect, replace_clip
from ingest import log_clip
from vocab import load_vocabulary


def upload(video: Path, client):
    handle = client.files.upload(file=str(video))
    while handle.state.name == "PROCESSING":
        time.sleep(2)
        handle = client.files.get(name=handle.name)
    if handle.state.name != "ACTIVE":
        raise RuntimeError(f"upload ended in state {handle.state.name}")
    return handle.uri


def upload_and_log(video: Path, vocabulary, client) -> list[dict]:
    """The real per-clip pipeline: upload to the Files API, then log_clip."""
    return log_clip(upload(video, client), vocabulary, client, source_file=video.name)


def run_batch(videos, vocabulary, client, db, log_clip, replace_clip,
              log=print) -> tuple[int, list[str]]:
    """Log every clip in `videos`, one at a time.

    A clip that raises is recorded as failed and the batch continues - a
    stuck or rate-limited clip should not cost the rest of the run. Returns
    (total shots written, names of clips that failed).
    """
    total = 0
    failed: list[str] = []
    for index, video in enumerate(videos, start=1):
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
    return total, failed


def exit_code(failed: list[str]) -> int:
    return 1 if failed else 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    load_dotenv()
    client = genai.Client()
    db = connect()
    vocabulary = load_vocabulary()

    videos = sorted(Path(sys.argv[1]).glob("*.mp4"))
    if not videos:
        print(f"no .mp4 files in {sys.argv[1]}")
        return 1

    total, failed = run_batch(videos, vocabulary, client, db,
                               log_clip=upload_and_log, replace_clip=replace_clip)

    print(f"\n{total} shots from {len(videos) - len(failed)}/{len(videos)} clips")
    if failed:
        print("failed: " + ", ".join(failed))
        print("re-run to retry - already-logged clips are replaced, not duplicated")
    return exit_code(failed)


if __name__ == "__main__":
    raise SystemExit(main())
