"""Camera-roll filenames collide across productions, so both the skip check
and the replace-delete have to be scoped by project_id.

Every camera names its first clip A001_C0001.mp4. Two productions in one
table therefore share source_file values, and anything keyed on source_file
alone silently reaches into the wrong movie's rows.
"""

from datetime import datetime

import db


class FakeClickHouse:
    """Records commands and inserts; returns canned query rows."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.commands: list[tuple[str, dict]] = []
        self.inserted: list[list] = []

    class _Result:
        def __init__(self, rows):
            self.result_rows = rows

    def query(self, sql, parameters=None):
        self.last_query = (sql, parameters or {})
        return self._Result(self.rows)

    def command(self, sql, parameters=None, settings=None):
        self.commands.append((sql, parameters or {}))

    def insert(self, table, data, column_names=None, settings=None):
        self.inserted.extend(data)


def _row(source_file, project_id):
    row = {column: "" for column in db.INSERT_COLUMNS}
    row.update(source_file=source_file, project_id=project_id)
    for column in ("take", "start_seconds", "end_seconds"):
        row[column] = 0
    for column in ("characters", "props", "quality_flags"):
        row[column] = []
    return row


def test_logged_sources_only_reports_this_projects_clips():
    last_ingested = datetime(2026, 1, 1, 12, 0, 0)
    client = FakeClickHouse(rows=[("A001_C0001.mp4", last_ingested)])

    result = db.logged_sources(client, project_id="lailamajnu")

    sql, parameters = client.last_query
    assert "project_id" in sql, "skip check must filter by project"
    assert parameters.get("pid") == "lailamajnu"
    # A name -> last-ingested mapping, not a bare set - the staleness check
    # in run_batch needs the timestamp to tell a re-cut clip from an
    # untouched one.
    assert result == {"A001_C0001.mp4": last_ingested}


def test_replace_clip_does_not_delete_another_projects_rows():
    """The dangerous one: an unscoped DELETE drops the other movie's shots."""
    client = FakeClickHouse()

    db.replace_clip(client, [_row("A001_C0001.mp4", "lailamajnu")])

    assert len(client.commands) == 1
    sql, parameters = client.commands[0]
    assert "project_id" in sql, "DELETE must be scoped to the project"
    assert parameters.get("pid") == "lailamajnu"
    assert parameters.get("src") == "A001_C0001.mp4"


def test_replace_clip_scopes_each_project_separately():
    """Same filename under two projects deletes twice, never across."""
    client = FakeClickHouse()

    db.replace_clip(
        client,
        [_row("A001_C0001.mp4", "lailamajnu"), _row("A001_C0001.mp4", "notld_1968")],
    )

    scoped = {(p.get("src"), p.get("pid")) for _, p in client.commands}
    assert scoped == {
        ("A001_C0001.mp4", "lailamajnu"),
        ("A001_C0001.mp4", "notld_1968"),
    }
