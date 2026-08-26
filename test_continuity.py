import json

import pytest

from continuity import check_group, group_for_comparison, shot_label


def shot(src="A001_C0001.mp4", start=0.0, scene="unknown", location="Cellar",
         continuity="Ben in dark jacket; rifle in right hand", characters=("Ben",)):
    return {"source_file": src, "start_seconds": start, "scene": scene,
            "location": location, "continuity": continuity,
            "characters": list(characters), "take": 1}


class FakeModels:
    def __init__(self, text):
        self._text, self.calls = text, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"text": self._text})()


class FakeClient:
    def __init__(self, text):
        self.models = FakeModels(text)


def test_groups_are_per_character_per_location():
    # A script supervisor tracks one person's state through a setup, not the
    # frame as a whole.
    groups = group_for_comparison([
        shot(src="a.mp4", characters=["Ben", "Barbara"]),
        shot(src="b.mp4", characters=["Ben", "Barbara"]),
    ])
    assert {g.character for g in groups} == {"Ben", "Barbara"}
    assert all(len(g.shots) == 2 for g in groups)


def test_shots_with_nobody_identified_are_never_compared():
    # The false positive this rule exists to stop: one shot described "a man
    # in light trousers", the next "individuals in dark clothing", nobody
    # identified in either. Different vagueness is not a contradiction.
    groups = group_for_comparison([
        shot(src="a.mp4", characters=["unknown"],
             continuity="The man is wearing light-coloured trousers"),
        shot(src="b.mp4", characters=["unknown"],
             continuity="The individuals are wearing dark clothing"),
    ])
    assert groups == []


def test_unknown_is_dropped_but_the_named_character_still_groups():
    groups = group_for_comparison([
        shot(src="a.mp4", characters=["Ben", "unknown"]),
        shot(src="b.mp4", characters=["Ben", "unknown"]),
    ])
    assert [g.character for g in groups] == ["Ben"]


def test_a_character_seen_once_in_a_location_cannot_contradict_anything():
    groups = group_for_comparison([
        shot(src="a.mp4", location="Cellar", characters=["Ben"]),
        shot(src="b.mp4", location="Kitchen", characters=["Ben"]),
    ])
    assert groups == []


def test_the_same_character_in_two_locations_is_two_groups():
    # Costume may legitimately change between locations - time passes.
    groups = group_for_comparison([
        shot(src="a.mp4", location="Cellar"), shot(src="b.mp4", location="Cellar"),
        shot(src="c.mp4", location="Kitchen"), shot(src="d.mp4", location="Kitchen"),
    ])
    assert len(groups) == 2
    assert {g.location for g in groups} == {"Cellar", "Kitchen"}


def test_shots_with_no_continuity_text_are_excluded():
    groups = group_for_comparison([
        shot(src="a.mp4"), shot(src="b.mp4", continuity=""),
        shot(src="c.mp4", continuity="   "),
    ])
    assert groups == []


def test_the_prompt_names_the_character_and_carries_each_shots_state():
    client = FakeClient("[]")
    (group,) = group_for_comparison([
        shot(src="a.mp4", start=1.0, continuity="Ben: lamp lit"),
        shot(src="b.mp4", start=2.0, continuity="Ben: lamp unlit"),
    ])
    check_group(group, client, model="test-model")

    prompt = next(p["text"] for p in client.models.calls[0]["contents"] if "text" in p)
    assert "Ben" in prompt
    assert "lamp lit" in prompt and "lamp unlit" in prompt
    assert all(shot_label(s) in prompt for s in group.shots)


def test_findings_naming_a_shot_outside_the_group_are_rejected():
    # The model can invent a plausible clip name. Sending an editor to a clip
    # that was never compared is worse than reporting nothing.
    (group,) = group_for_comparison([shot(src="a.mp4"), shot(src="b.mp4", start=5.0)])
    reply = json.dumps([{"subject": "Ben", "detail": "jacket changes",
                         "shots": ["a.mp4 @0.0s", "ZZZ_invented.mp4 @9.9s"]}])
    with pytest.raises(ValueError, match="not in this group"):
        check_group(group, FakeClient(reply))


def test_a_clean_group_reports_nothing():
    (group,) = group_for_comparison([shot(src="a.mp4"), shot(src="b.mp4", start=5.0)])
    assert check_group(group, FakeClient("[]")) == []


def test_a_real_finding_comes_back_with_its_shots():
    (group,) = group_for_comparison([shot(src="a.mp4"), shot(src="b.mp4", start=5.0)])
    reply = json.dumps([{"subject": "Ben", "detail": "rifle switches hands",
                         "shots": [shot_label(s) for s in group.shots]}])
    (finding,) = check_group(group, FakeClient(reply))
    assert finding["subject"] == "Ben"
    assert "rifle" in finding["detail"]
