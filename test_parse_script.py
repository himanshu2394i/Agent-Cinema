import json
import pytest

from parse_script import parse_screenplay, vocabulary_from_json


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self._text)


class FakeClient:
    def __init__(self, text):
        self.models = FakeModels(text)


GOOD = json.dumps({
    "characters": ["SARAH", "SARAH (V.O.)", "DET. RUIZ"],
    "locations": ["SARAH'S CAR", "DINER"],
    "props": ["the letter"],
    "scenes": ["1", "14B"],
})


def test_normalises_through_project_vocabulary():
    pv = vocabulary_from_json(GOOD)
    assert pv.characters == ["Sarah", "Det. Ruiz"]
    assert pv.locations == ["Sarah's Car", "Diner"]
    assert pv.props == ["The Letter"]
    assert pv.scenes == ["1", "14B"]


def test_missing_keys_default_to_empty():
    pv = vocabulary_from_json(json.dumps({"characters": ["Sarah"]}))
    assert pv.characters == ["Sarah"]
    assert pv.locations == [] and pv.props == [] and pv.scenes == []


def test_empty_cast_fails_loudly():
    # A screenplay with no characters means extraction failed. Returning an
    # empty vocabulary would let ingest run and produce garbage silently.
    with pytest.raises(ValueError, match="no characters"):
        vocabulary_from_json(json.dumps({"characters": [], "locations": ["Diner"]}))


def test_non_list_field_is_rejected():
    with pytest.raises(ValueError, match="locations"):
        vocabulary_from_json(json.dumps({"characters": ["Sarah"], "locations": "Diner"}))


def test_malformed_json_is_rejected():
    with pytest.raises(ValueError, match="not valid JSON"):
        vocabulary_from_json("sorry, I could not read that screenplay")


def test_sends_pdf_bytes_and_json_schema_to_the_model():
    client = FakeClient(GOOD)
    parse_screenplay(b"%PDF-1.7 fake", client, model="test-model")

    (call,) = client.models.calls
    assert call["model"] == "test-model"

    part = next(p for p in call["contents"] if "inline_data" in p)
    assert part["inline_data"]["mime_type"] == "application/pdf"
    assert part["inline_data"]["data"] == b"%PDF-1.7 fake"

    cfg = call["config"]
    assert cfg["response_mime_type"] == "application/json"
    assert set(cfg["response_schema"]["properties"]) == {
        "characters", "locations", "props", "scenes",
    }
