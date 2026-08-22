"""End-to-end smoke test: screenplay -> vocabulary -> clip -> validated rows.

    python smoke.py assets/notld_1968_screenplay.pdf assets/sintel_trailer.mp4

This is the whole ingest half in one run. It does not touch ClickHouse - the
point is to find out whether Gemini logs footage well enough to be worth
storing, which is the project's biggest untested assumption.

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

from ingest import log_clip
from parse_script import parse_screenplay
from vocab import ProjectVocabulary

CACHE = Path("assets/vocabulary.json")


def vocabulary_for(pdf: Path, client) -> ProjectVocabulary:
    if CACHE.exists():
        print(f"vocabulary: cached ({CACHE})")
        return ProjectVocabulary(**json.loads(CACHE.read_text()))

    print(f"vocabulary: parsing {pdf.name} ...")
    start = time.perf_counter()
    result = parse_screenplay(pdf.read_bytes(), client)
    print(f"  parsed in {time.perf_counter() - start:.0f}s")
    CACHE.write_text(json.dumps(dataclasses.asdict(result), indent=2))
    return result


def upload(video: Path, client):
    print(f"upload: {video.name} ({video.stat().st_size / 1e6:.1f} MB) ...")
    handle = client.files.upload(file=str(video))
    while handle.state.name == "PROCESSING":
        time.sleep(2)
        handle = client.files.get(name=handle.name)
    if handle.state.name != "ACTIVE":
        raise SystemExit(f"upload ended in state {handle.state.name}")
    print(f"  ready: {handle.uri}")
    return handle.uri


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    load_dotenv()
    client = genai.Client()
    pdf, video = Path(sys.argv[1]), Path(sys.argv[2])

    vocabulary = vocabulary_for(pdf, client)
    for name in ("characters", "locations", "props", "scenes"):
        values = getattr(vocabulary, name)
        print(f"  {name:11} {len(values):4}  {', '.join(values[:6])}")

    uri = upload(video, client)

    print("logging shots ...")
    start = time.perf_counter()
    rows = log_clip(uri, vocabulary, client)
    print(f"  {len(rows)} shots in {time.perf_counter() - start:.0f}s\n")

    for row in rows:
        span = f"{row['start_seconds']:>6.1f}-{row['end_seconds']:<6.1f}"
        print(f"{span} {row['shot_size']:<17} {row['camera_movement']:<9} "
              f"{row['int_ext']:<10} {row['time_of_day']:<14} "
              f"{','.join(row['characters']) or '-'}")
        print(f"       {row['action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
