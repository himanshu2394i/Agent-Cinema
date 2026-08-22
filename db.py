"""ClickHouse connection, table creation and bulk load.

    python db.py init            # create the shots table
    python db.py load 2000000    # generate and insert synthetic dailies
    python db.py demo            # timed sample queries

Credentials come from .env (gitignored) so no secret is ever written into
source. See .env.example for the keys.
"""

import os
import sys
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
    "every take Sarah handles the letter": f"""
        SELECT count() FROM {TABLE}
        WHERE has(characters, 'Sarah') AND has(props, 'The Letter')""",
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


def load(client, count: int) -> None:
    rows = generate_rows(demo_vocabulary(), count)
    done = 0
    for chunk in batched(rows, BATCH):
        client.insert(
            TABLE,
            [[row[c] for c in INSERT_COLUMNS] for row in chunk],
            column_names=INSERT_COLUMNS,
        )
        done += len(chunk)
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
