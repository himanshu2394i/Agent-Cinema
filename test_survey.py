import json

import pytest

from survey import (
    count_terms, observe_clip, propose_vocabulary, sample_evenly,
)


def obs(characters=(), locations=(), props=()):
    return {"characters": list(characters), "locations": list(locations),
            "props": list(props)}


def test_a_term_seen_in_enough_clips_is_kept():
    pv = propose_vocabulary([
        obs(characters=["Woman In Red Coat"]),
        obs(characters=["Woman In Red Coat"]),
    ], min_clips=2)
    assert pv.characters == ["Woman In Red Coat"]


def test_a_term_seen_in_too_few_clips_is_dropped():
    # A face that appears once is a passer-by, not a subject worth a column.
    pv = propose_vocabulary([
        obs(characters=["Woman In Red Coat", "Man With Clipboard"]),
        obs(characters=["Woman In Red Coat"]),
    ], min_clips=2)
    assert pv.characters == ["Woman In Red Coat"]


def test_counting_is_per_clip_not_per_mention():
    # One talkative clip must not promote a term on its own.
    counts = count_terms([obs(characters=["Ben", "Ben", "Ben"])])
    assert counts["characters"]["Ben"] == 1


def test_spelling_variants_merge_before_they_are_counted():
    # The trap: normalise after counting and each variant lands below the
    # threshold, so a term that really is in every clip gets dropped.
    pv = propose_vocabulary([
        obs(characters=["woman in red coat"]),
        obs(characters=["Woman In Red Coat"]),
        obs(characters=["  WOMAN IN RED COAT  "]),
    ], min_clips=3)
    assert pv.characters == ["Woman In Red Coat"]


def test_missing_keys_are_tolerated():
    pv = propose_vocabulary([{"characters": ["Ben"]}, {"characters": ["Ben"]}],
                            min_clips=2)
    assert pv.characters == ["Ben"]
    assert pv.locations == [] and pv.props == []


def test_unscripted_footage_has_no_scenes():
    pv = propose_vocabulary([obs(characters=["Ben"]), obs(characters=["Ben"])],
                            min_clips=2)
    assert pv.scenes == []


def test_sample_evenly_spreads_across_the_directory():
    videos = [f"c{i}" for i in range(20)]
    assert sample_evenly(videos, 4) == ["c0", "c5", "c10", "c15"]
    # Asking for more than exist returns all of them, in order.
    assert sample_evenly(videos[:3], 10) == ["c0", "c1", "c2"]


class FakeModels:
    def __init__(self, text):
        self._text, self.calls = text, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"text": self._text})()


class FakeClient:
    def __init__(self, text):
        self.models = FakeModels(text)


def test_the_survey_call_is_unconstrained():
    # Pass one is discovery: constraining it to a vocabulary would defeat the
    # entire point, since the vocabulary is what we are trying to find.
    client = FakeClient(json.dumps(obs(characters=["Woman In Red Coat"])))
    observe_clip("gs://x/c1.mp4", client, model="test-model")

    schema = client.models.calls[0]["config"]["response_schema"]
    props = schema["properties"]
    assert set(props) == {"characters", "locations", "props"}
    for field in props.values():
        assert "enum" not in field["items"], "survey must not constrain values"


def test_survey_rejects_a_non_object_reply():
    with pytest.raises(ValueError, match="object"):
        observe_clip("gs://x/c1.mp4", FakeClient("[1, 2, 3]"))


def test_survey_carries_forward_what_it_has_already_named():
    # Each clip is an independent call, so the model cannot remember what it
    # called someone last time. Left to itself it describes one person three
    # ways across three clips and none of them reach the threshold. Feeding
    # the terms so far back in is what makes the count mean anything.
    client = FakeClient(json.dumps(obs(characters=["Woman In Red Coat"])))
    observe_clip("gs://x/c2.mp4", client, known={
        "characters": ["Woman In Red Coat"], "locations": ["Hotel Lobby"], "props": [],
    })

    prompt = next(p["text"] for p in client.models.calls[0]["contents"] if "text" in p)
    assert "Woman In Red Coat" in prompt
    assert "Hotel Lobby" in prompt


def test_the_first_clip_has_nothing_to_carry_forward():
    client = FakeClient(json.dumps(obs(characters=["Woman In Red Coat"])))
    observe_clip("gs://x/c1.mp4", client)
    prompt = next(p["text"] for p in client.models.calls[0]["contents"] if "text" in p)
    # No empty "already seen:" section confusing the model on clip one.
    assert "already" not in prompt.lower()
