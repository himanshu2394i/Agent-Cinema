import json
import pytest

from ingest import log_clip, rows_from_response
from vocab import ProjectVocabulary

VOCAB = ProjectVocabulary.from_raw(
    characters=["SARAH", "DET. RUIZ"], locations=["DINER"],
    props=["the letter"], scenes=["14B"],
)

SHOT = {
    "scene": "14B", "take": 3, "start_seconds": 0.0, "end_seconds": 12.5,
    "shot_size": "wide", "camera_movement": "static", "time_of_day": "golden_hour",
    "int_ext": "interior", "location": "Diner", "characters": ["Sarah"],
    "props": ["The Letter"], "quality_flags": ["none"],
    "dialogue": "You kept it.", "action": "Sarah slides the letter across.",
}


def _reply(*shots):
    return json.dumps(list(shots))


class FakeModels:
    def __init__(self, text):
        self._text, self.calls = text, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"text": self._text})()


class FakeClient:
    def __init__(self, text):
        self.models = FakeModels(text)


def test_rows_carry_the_source_file():
    (row,) = rows_from_response(_reply(SHOT), VOCAB, "gs://dailies/A001_C003.mp4")
    assert row["source_file"] == "gs://dailies/A001_C003.mp4"
    assert row["scene"] == "14B" and row["characters"] == ["Sarah"]


def test_rejects_value_outside_the_craft_vocabulary():
    # Defence in depth: the enum should make this impossible, but a bad value
    # in a LowCardinality column breaks every future query silently.
    bad = {**SHOT, "shot_size": "super wide"}
    with pytest.raises(ValueError, match="shot_size"):
        rows_from_response(_reply(bad), VOCAB, "gs://x.mp4")


def test_rejects_character_outside_the_screenplay_vocabulary():
    bad = {**SHOT, "characters": ["Sarah", "Bob"]}
    with pytest.raises(ValueError, match="characters"):
        rows_from_response(_reply(bad), VOCAB, "gs://x.mp4")


def test_unknown_is_always_an_acceptable_value():
    ok = {**SHOT, "characters": ["unknown"], "location": "unknown"}
    (row,) = rows_from_response(_reply(ok), VOCAB, "gs://x.mp4")
    assert row["characters"] == ["unknown"]


def test_rejects_non_increasing_timestamps():
    bad = {**SHOT, "start_seconds": 9.0, "end_seconds": 9.0}
    with pytest.raises(ValueError, match="timestamps"):
        rows_from_response(_reply(bad), VOCAB, "gs://x.mp4")


def test_rejects_missing_field():
    bad = {k: v for k, v in SHOT.items() if k != "dialogue"}
    with pytest.raises(ValueError, match="dialogue"):
        rows_from_response(_reply(bad), VOCAB, "gs://x.mp4")


def test_clip_with_no_shots_fails_loudly():
    with pytest.raises(ValueError, match="no shots"):
        rows_from_response(_reply(), VOCAB, "gs://x.mp4")


def test_sends_gcs_uri_and_generated_schema():
    client = FakeClient(_reply(SHOT))
    log_clip("gs://dailies/A001_C003.mp4", VOCAB, client, model="test-model")

    (call,) = client.models.calls
    part = next(p for p in call["contents"] if "file_data" in p)
    assert part["file_data"]["file_uri"] == "gs://dailies/A001_C003.mp4"
    assert part["file_data"]["mime_type"] == "video/mp4"

    schema = call["config"]["response_schema"]
    assert schema["type"] == "array"
    # The enum handed to the model is the screenplay's, not a hardcoded list.
    assert schema["items"]["properties"]["characters"]["items"]["enum"] == [
        "Sarah", "Det. Ruiz", "unknown",
    ]


def test_rejects_non_gcs_uri():
    with pytest.raises(ValueError, match="gs://"):
        log_clip("C:/footage/clip.mp4", VOCAB, FakeClient(_reply(SHOT)))


FILES_URI = "https://generativelanguage.googleapis.com/v1beta/files/abc123"


def test_accepts_a_files_api_uri():
    # The Files API is the only upload path that works without a GCS bucket,
    # which is what local development and the smoke test rely on.
    client = FakeClient(_reply(SHOT))
    rows = log_clip(FILES_URI, VOCAB, client)
    assert rows[0]["source_file"] == FILES_URI
    part = next(p for p in client.models.calls[0]["contents"] if "file_data" in p)
    assert part["file_data"]["file_uri"] == FILES_URI
