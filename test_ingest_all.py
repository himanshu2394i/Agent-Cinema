"""Tests for the batch loop in ingest_all.py.

log_clip and the database write (replace_clip) are the two places real IO
happens - stub both and the loop can be tested with no network and no
ClickHouse. logged_sources is a third injected dependency: it stands in for
the ClickHouse lookup that lets a re-run skip clips already ingested, so a
retry after a partial failure costs one API call per genuinely-missing clip
instead of one per clip in the directory. It returns a name -> last-ingested
mapping (not a bare set) so the skip decision can tell a clip that has been
re-cut since it was logged from one that has not. Follows the plain-stub-class
style used in test_ingest.py rather than a mocking library.
"""

from datetime import datetime, timedelta, timezone

from ingest_all import _clip_is_stale, exit_code, run_batch

# A fixed "now" that already-logged clips in these tests were ingested at.
LOGGED_AT = datetime(2026, 1, 1, 12, 0, 0)


class FakeVideo:
    """Stands in for a Path - .name and .stat().st_mtime are used by run_batch."""

    def __init__(self, name, mtime=0.0):
        self.name = name
        self._mtime = mtime

    def stat(self):
        return _Stat(self._mtime)


class _Stat:
    def __init__(self, st_mtime):
        self.st_mtime = st_mtime


def fake_replace_clip(db, rows):
    return len(rows)


def no_sources_logged(db, project_id):
    return {}


def test_a_failing_clip_does_not_abort_the_batch():
    videos = [FakeVideo("A001_C0001.mp4"), FakeVideo("A001_C0002.mp4"),
              FakeVideo("A001_C0003.mp4")]

    def log_clip(video, vocabulary, client):
        if video.name == "A001_C0002.mp4":
            raise RuntimeError("boom")
        return [{"source_file": video.name}]

    total, failed, skipped = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip,
        logged_sources=no_sources_logged, log=lambda *_: None,
    )

    # The two clips either side of the failure were still processed.
    assert total == 2
    assert failed == ["A001_C0002.mp4"]
    assert skipped == []


def test_failed_clip_names_are_collected():
    videos = [FakeVideo("good.mp4"), FakeVideo("bad.mp4")]

    def log_clip(video, vocabulary, client):
        if video.name == "bad.mp4":
            raise ValueError("could not parse response")
        return [{"source_file": video.name}, {"source_file": video.name}]

    total, failed, skipped = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip,
        logged_sources=no_sources_logged, log=lambda *_: None,
    )

    assert total == 2
    assert failed == ["bad.mp4"]
    assert skipped == []


def test_exit_code_is_nonzero_when_any_clip_failed():
    assert exit_code(["bad.mp4"]) != 0


def test_exit_code_is_zero_when_all_clips_succeed():
    assert exit_code([]) == 0


def test_an_already_logged_clip_is_skipped_and_does_not_call_log_clip():
    # old.mp4 keeps its default mtime (epoch) - older than LOGGED_AT, so it
    # is untouched since it was last ingested and must be skipped.
    videos = [FakeVideo("old.mp4"), FakeVideo("new.mp4")]
    log_clip_calls = []

    def log_clip(video, vocabulary, client):
        log_clip_calls.append(video.name)
        return [{"source_file": video.name}]

    def logged_sources(db, project_id):
        return {"old.mp4": LOGGED_AT}

    total, failed, skipped = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip,
        logged_sources=logged_sources, log=lambda *_: None,
    )

    # The whole point: skipping a clip must never spend an API call on it.
    assert log_clip_calls == ["new.mp4"]
    assert total == 1
    assert failed == []
    assert skipped == ["old.mp4"]


def test_a_clip_not_yet_logged_is_still_ingested():
    videos = [FakeVideo("brand_new.mp4")]
    log_clip_calls = []

    def log_clip(video, vocabulary, client):
        log_clip_calls.append(video.name)
        return [{"source_file": video.name}]

    def logged_sources(db, project_id):
        return {}

    total, failed, skipped = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip,
        logged_sources=logged_sources, log=lambda *_: None,
    )

    assert log_clip_calls == ["brand_new.mp4"]
    assert total == 1
    assert skipped == []


def test_force_reingests_an_already_logged_clip():
    videos = [FakeVideo("old.mp4")]
    log_clip_calls = []

    def log_clip(video, vocabulary, client):
        log_clip_calls.append(video.name)
        return [{"source_file": video.name}]

    def logged_sources(db, project_id):
        return {"old.mp4": LOGGED_AT}

    total, failed, skipped = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip,
        logged_sources=logged_sources, force=True, log=lambda *_: None,
    )

    assert log_clip_calls == ["old.mp4"]
    assert total == 1
    assert skipped == []


def test_skip_check_is_asked_about_this_project_only():
    """The bug this pins: A001_C0001.mp4 logged under another production
    made every clip of a new production look already-logged, so the new
    movie could never be ingested at all."""
    asked = []

    def logged_sources(db, project_id):
        asked.append(project_id)
        return {"A001_C0001.mp4": LOGGED_AT} if project_id == "notld_1968" else {}

    def log_clip(video, vocabulary, client):
        return [{"source_file": video.name}]

    total, failed, skipped = run_batch(
        [FakeVideo("A001_C0001.mp4")], vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip,
        logged_sources=logged_sources, project_id="lailamajnu",
        log=lambda *_: None,
    )

    assert asked == ["lailamajnu"]
    assert skipped == []
    assert total == 1


def test_a_clip_older_than_its_last_ingest_is_still_skipped():
    """Untouched since it was logged - the common case, no re-ingest."""
    older_mtime = (LOGGED_AT - timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp()
    videos = [FakeVideo("A001_C0001.mp4", mtime=older_mtime)]
    log_clip_calls = []

    def log_clip(video, vocabulary, client):
        log_clip_calls.append(video.name)
        return [{"source_file": video.name}]

    def logged_sources(db, project_id):
        return {"A001_C0001.mp4": LOGGED_AT}

    total, failed, skipped = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip,
        logged_sources=logged_sources, log=lambda *_: None,
    )

    assert log_clip_calls == []
    assert skipped == ["A001_C0001.mp4"]
    assert total == 0


def test_a_clip_re_cut_since_its_last_ingest_is_reingested_via_replace_clip():
    """The bug this pins: 171 re-cut clips kept the old picture's description
    because the same camera-roll name was already logged and got skipped."""
    newer_mtime = (LOGGED_AT + timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp()
    videos = [FakeVideo("A001_C0001.mp4", mtime=newer_mtime)]
    log_clip_calls = []
    replace_clip_calls = []

    def log_clip(video, vocabulary, client):
        log_clip_calls.append(video.name)
        return [{"source_file": video.name}]

    def replace_clip(db, rows):
        replace_clip_calls.append(rows)
        return len(rows)

    def logged_sources(db, project_id):
        return {"A001_C0001.mp4": LOGGED_AT}

    total, failed, skipped = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=replace_clip,
        logged_sources=logged_sources, log=lambda *_: None,
    )

    assert log_clip_calls == ["A001_C0001.mp4"]
    assert len(replace_clip_calls) == 1
    assert skipped == []
    assert total == 1


def test_stale_check_compares_mtime_and_ingested_at_in_utc():
    """Pins the trap: ClickHouse's DateTime comes back naive-but-UTC, and
    st_mtime is a POSIX timestamp. Building the mtime side with local time
    instead of UTC would misjudge every clip by the machine's UTC offset -
    correct-looking on a UTC machine, silently wrong everywhere else (this
    dev machine is UTC+5:30, so a naive local conversion fails this test).
    """
    logged_at = datetime(2026, 1, 1, 12, 0, 0)  # naive, as ClickHouse returns it - is UTC

    just_before = datetime(2026, 1, 1, 11, 59, 59, tzinfo=timezone.utc).timestamp()
    assert _clip_is_stale(FakeVideo("x.mp4", mtime=just_before), logged_at) is False

    just_after = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc).timestamp()
    assert _clip_is_stale(FakeVideo("x.mp4", mtime=just_after), logged_at) is True
