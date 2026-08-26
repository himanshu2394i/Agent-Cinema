"""One-shot: add project_id to live shots table and backfill."""
from dotenv import load_dotenv

load_dotenv()
from db import connect  # noqa: E402

c = connect()
print("cols:", [r[0] for r in c.query("DESCRIBE TABLE shots").result_rows])
c.command(
    "ALTER TABLE shots ADD COLUMN IF NOT EXISTS project_id "
    "LowCardinality(String) DEFAULT 'notld_1968'"
)
print("ADD COLUMN ok")
c.command(
    "ALTER TABLE shots UPDATE project_id = 'archive' "
    "WHERE source_file LIKE 'gs://%' SETTINGS mutations_sync=1"
)
print("backfill archive ok")
c.command(
    "ALTER TABLE shots UPDATE project_id = 'notld_1968' "
    "WHERE source_file LIKE 'A001_%' SETTINGS mutations_sync=1"
)
print("backfill notld ok")
rows = c.query(
    "SELECT project_id, count() AS n FROM shots "
    "GROUP BY project_id ORDER BY n DESC"
).result_rows
print("counts", rows)
