"""Which backend a clip is handed to Gemini through.

log_clip already accepts either a gs:// object or a Files API URI. What was
missing is the gs:// producer, which is the only path that works on Vertex:
Vertex has no Files API, so client.files.upload raises there regardless of
quota. The Files API is the Developer-client path and is capped per day on
the free tier. Hence a dispatch rather than a single uploader.
"""

from pathlib import Path

import pytest

import ingest


class FakeBlob:
    def __init__(self, name, recorder):
        self.name = name
        self._recorder = recorder

    def upload_from_filename(self, filename, content_type=None):
        self._recorder.append((self.name, str(filename), content_type))


class FakeBucket:
    def __init__(self, name, recorder):
        self.name = name
        self._recorder = recorder

    def blob(self, name):
        return FakeBlob(name, self._recorder)


class FakeStorage:
    def __init__(self):
        self.uploads: list[tuple] = []

    def bucket(self, name):
        return FakeBucket(name, self.uploads)


def test_gcs_upload_returns_a_uri_log_clip_accepts():
    storage = FakeStorage()

    uri = ingest.upload_to_gcs(
        Path("assets/projects/lailamajnu/clips/A001_C0007.mp4"),
        bucket="dailies-ingest",
        storage_client=storage,
    )

    assert uri == "gs://dailies-ingest/A001_C0007.mp4"
    assert uri.startswith(ingest.GCS_PREFIX)
    name, _, content_type = storage.uploads[0]
    assert name == "A001_C0007.mp4"
    assert content_type == ingest.VIDEO_MIME


def test_gcs_upload_keeps_clips_of_different_projects_apart():
    """Camera roll names repeat across productions - same bug class as the
    ClickHouse one, and a bucket is just as flat a namespace."""
    storage = FakeStorage()

    uri = ingest.upload_to_gcs(
        Path("A001_C0001.mp4"), bucket="b",
        storage_client=storage, project_id="lailamajnu",
    )

    assert uri == "gs://b/lailamajnu/A001_C0001.mp4"


def test_clip_uri_prefers_gcs_when_a_bucket_is_configured():
    storage = FakeStorage()

    uri = ingest.clip_uri(
        Path("A001_C0001.mp4"), client=None,
        bucket="b", storage_client=storage, project_id="p",
    )

    assert uri.startswith("gs://")


def test_clip_uri_falls_back_to_the_files_api_with_no_bucket():
    calls = []

    class FakeGenaiClient:
        class files:
            @staticmethod
            def upload(file):
                calls.append(file)
                class Handle:
                    uri = ingest.FILES_API_PREFIX + "v1beta/files/abc"
                    class state:
                        name = "ACTIVE"
                return Handle()

    uri = ingest.clip_uri(Path("A001_C0001.mp4"), client=FakeGenaiClient(), bucket=None)

    assert uri.startswith(ingest.FILES_API_PREFIX)
    assert calls == ["A001_C0001.mp4"]


def test_gcs_upload_needs_a_bucket_name():
    with pytest.raises(ValueError, match="bucket"):
        ingest.upload_to_gcs(Path("x.mp4"), bucket="", storage_client=FakeStorage())


def test_batch_uses_the_bucket_when_one_is_configured(monkeypatch):
    """Wiring check: the dispatch is useless if the batch never calls it."""
    import ingest_all

    monkeypatch.setenv("GCS_INGEST_BUCKET", "dailies-ingest")
    seen = {}

    def fake_clip_uri(video, client, bucket=None, storage_client=None, project_id=None):
        seen.update(bucket=bucket, project_id=project_id)
        return "gs://dailies-ingest/lailamajnu/A001_C0001.mp4"

    def fake_log_clip(uri, vocabulary, client, source_file=None, project_id=None):
        seen["uri"] = uri
        return []

    monkeypatch.setattr(ingest_all, "clip_uri", fake_clip_uri)
    monkeypatch.setattr(ingest_all, "log_clip", fake_log_clip)

    ingest_all.upload_and_log(Path("A001_C0001.mp4"), None, None, "lailamajnu")

    assert seen["bucket"] == "dailies-ingest"
    assert seen["project_id"] == "lailamajnu"
    assert seen["uri"].startswith("gs://")


def test_batch_without_a_bucket_still_uses_the_files_api(monkeypatch):
    import ingest_all

    monkeypatch.delenv("GCS_INGEST_BUCKET", raising=False)
    seen = {}

    def fake_clip_uri(video, client, bucket=None, storage_client=None, project_id=None):
        seen["bucket"] = bucket
        return ingest.FILES_API_PREFIX + "v1beta/files/abc"

    monkeypatch.setattr(ingest_all, "clip_uri", fake_clip_uri)
    monkeypatch.setattr(ingest_all, "log_clip", lambda *a, **k: [])

    ingest_all.upload_and_log(Path("A001_C0001.mp4"), None, None, "lailamajnu")

    assert seen["bucket"] in (None, "")
