"""continuity.py must compare one production at a time.

The default filename pattern was A001_% back when NOTLD was the only movie in
the table. Two productions later that pattern spans both, and the comparison
reports Ben-in-the-farmhouse against Qays-in-Kashmir as continuity errors.
Same root cause as the ingest bugs: source_file is not unique across films.
"""

import continuity


class FakeClickHouse:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.last = None

    class _Result:
        def __init__(self, rows):
            self.result_rows = rows

    def query(self, sql, parameters=None):
        self.last = (sql, parameters or {})
        return self._Result(self.rows)


def test_state_rows_are_filtered_by_project():
    db = FakeClickHouse()

    continuity.fetch_state_rows(db, project_id="lailamajnu")

    sql, parameters = db.last
    assert "project_id" in sql, "continuity must not span two productions"
    assert parameters.get("pid") == "lailamajnu"


def test_pattern_still_narrows_within_one_project():
    """The pattern is still available - it just no longer does the scoping."""
    db = FakeClickHouse()

    continuity.fetch_state_rows(db, project_id="notld_1968", pattern="A001_C000%")

    sql, parameters = db.last
    assert parameters.get("p") == "A001_C000%"
    assert parameters.get("pid") == "notld_1968"
    assert "source_file LIKE" in sql


def test_rows_come_back_as_dicts_the_grouper_understands():
    db = FakeClickHouse(rows=[
        ("A001_C0001.mp4", 1.0, "3", "Palm Grove", "cloak torn", ["Qays"], 1),
    ])

    rows = continuity.fetch_state_rows(db, project_id="lailamajnu")

    assert rows == [{
        "source_file": "A001_C0001.mp4", "start_seconds": 1.0, "scene": "3",
        "location": "Palm Grove", "continuity": "cloak torn",
        "characters": ["Qays"], "take": 1,
    }]
    # the grouper reads these keys, so a rename here breaks it silently
    assert continuity.group_for_comparison(rows) == []
