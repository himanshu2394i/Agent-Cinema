"""Tests for the batch loop in ingest_all.py.

log_clip and the database write (replace_clip) are the two places real IO
happens - stub both and the loop can be tested with no network and no
ClickHouse. Follows the plain-stub-class style used in test_ingest.py rather
than a mocking library.
"""

from ingest_all import exit_code, run_batch


class FakeVideo:
    """Stands in for a Path - only .name is used by run_batch."""

    def __init__(self, name):
        self.name = name


def fake_replace_clip(db, rows):
    return len(rows)


def test_a_failing_clip_does_not_abort_the_batch():
    videos = [FakeVideo("A001_C0001.mp4"), FakeVideo("A001_C0002.mp4"),
              FakeVideo("A001_C0003.mp4")]

    def log_clip(video, vocabulary, client):
        if video.name == "A001_C0002.mp4":
            raise RuntimeError("boom")
        return [{"source_file": video.name}]

    total, failed = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip, log=lambda *_: None,
    )

    # The two clips either side of the failure were still processed.
    assert total == 2
    assert failed == ["A001_C0002.mp4"]


def test_failed_clip_names_are_collected():
    videos = [FakeVideo("good.mp4"), FakeVideo("bad.mp4")]

    def log_clip(video, vocabulary, client):
        if video.name == "bad.mp4":
            raise ValueError("could not parse response")
        return [{"source_file": video.name}, {"source_file": video.name}]

    total, failed = run_batch(
        videos, vocabulary=None, client=None, db=None,
        log_clip=log_clip, replace_clip=fake_replace_clip, log=lambda *_: None,
    )

    assert total == 2
    assert failed == ["bad.mp4"]


def test_exit_code_is_nonzero_when_any_clip_failed():
    assert exit_code(["bad.mp4"]) != 0


def test_exit_code_is_zero_when_all_clips_succeed():
    assert exit_code([]) == 0
