"""ClickHouse connection, table creation and bulk load.

    python db.py init            # create the shots table
    python db.py load 2000000    # generate and insert synthetic dailies
    python db.py demo            # timed sample queries

Credentials come from .env (gitignored) so no secret is ever written into
source. See .env.example for the keys.
"""

import os
import sys
import uuid
from itertools import batched

import clickhouse_connect
from dotenv import load_dotenv

from shot_schema import MODEL_FIELDS, clickhouse_ddl
from synth import demo_vocabulary, generate_rows
from vocab import ProjectVocabulary

TABLE = "shots"
BATCH = 50_000

# Same order as the DDL, derived from the same table, so a new field cannot
# land in the wrong column.
INSERT_COLUMNS = ["source_file", *[f.name for f in MODEL_FIELDS]]

DEMO_QUERIES = {
    "total rows": f"SELECT count() FROM {TABLE}",
    "wide shots at golden hour, 2 characters": f"""
        SELECT count() FROM {TABLE}
        WHERE shot_size = 'wide' AND time_of_day = 'golden_hour'
          AND length(characters) = 2""",
    "clean takes of scene P07-14B": f"""
        SELECT take, source_file, round(end_seconds - start_seconds, 1) AS secs
        FROM {TABLE}
        WHERE scene = 'P07-14B' AND has(quality_flags, 'none')
        ORDER BY take LIMIT 5""",
    "every take Ben handles the rifle": f"""
        SELECT count() FROM {TABLE}
        WHERE has(characters, 'Ben') AND has(props, 'Rifle')""",
}


def connect():
    load_dotenv()
    host = os.getenv("CLICKHOUSE_HOST")
    if not host:
        raise SystemExit("CLICKHOUSE_HOST is not set - see .env.example")
    return clickhouse_connect.get_client(
        host=host,
        port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        secure=True,
    )


def insert_rows(client, rows) -> int:
    """Insert shot rows. Column order comes from INSERT_COLUMNS, not the dict.

    Every insert carries a fresh deduplication token. ClickHouse hashes each
    inserted block and silently drops an identical repeat - which is helpful
    for retrying a failed insert, and disastrous for re-logging a clip whose
    shots came out the same, because the write is dropped with no error.
    """
    rows = list(rows)
    client.insert(
        TABLE,
        [[row[column] for column in INSERT_COLUMNS] for row in rows],
        column_names=INSERT_COLUMNS,
        settings={"insert_deduplication_token": str(uuid.uuid4())},
    )
    return len(rows)


def logged_sources(client) -> set[str]:
    """Distinct source_file values already in the table.

    Lets a batch ingest skip clips it has already logged, so a re-run after
    a partial failure costs one API call per genuinely-missing clip instead
    of one per clip in the directory.
    """
    result = client.query(f"SELECT DISTINCT source_file FROM {TABLE}")
    return {row[0] for row in result.result_rows}


def replace_clip(client, rows) -> int:
    """Insert one clip's shots, dropping any earlier logging of that clip.

    Without this a second smoke run silently doubles the shots for a file.
    """
    rows = list(rows)
    sources = {row["source_file"] for row in rows}
    for source in sources:
        # Lightweight DELETE, waited out on every replica. ponytail: fine per
        # clip at ingest; batch into one DELETE ... IN if it ever runs hot.
        client.command(
            f"DELETE FROM {TABLE} WHERE source_file = %(src)s",
            parameters={"src": source},
            settings={"lightweight_deletes_sync": 2},
        )
    return insert_rows(client, rows)


def load(client, count: int) -> None:
    rows = generate_rows(demo_vocabulary(), count)
    done = 0
    for chunk in batched(rows, BATCH):
        done += insert_rows(client, chunk)
        print(f"  inserted {done:,}/{count:,}", flush=True)


def demo(client) -> None:
    import time

    for label, sql in DEMO_QUERIES.items():
        start = time.perf_counter()
        result = client.query(sql)
        elapsed = (time.perf_counter() - start) * 1000
        print(f"\n{label}  [{elapsed:.0f} ms]")
        for row in result.result_rows[:5]:
            print(f"  {row}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    client = connect()
    command = args[0]

    if command == "init":
        client.command(clickhouse_ddl(TABLE))
        print(f"table {TABLE} ready")
    elif command == "load":
        load(client, int(args[1]))
    elif command == "demo":
        demo(client)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
