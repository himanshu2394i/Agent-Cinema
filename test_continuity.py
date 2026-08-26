import json

import pytest

from continuity import check_group, group_for_comparison, shot_label


def shot(src="A001_C0001.mp4", start=0.0, scene="unknown", location="Cellar",
         continuity="Ben in dark jacket; rifle in right hand", characters=("Ben",)):
    return {"source_file": src, "start_seconds": start, "scene": scene,
            "location": location, "continuity": continuity,
            "characters": list(characters), "take": 1}


def test_groups_shots_that_share_a_scene_and_location():
    groups = group_for_comparison([
        shot(src="a.mp4", location="Cellar"),
        shot(src="b.mp4", location="Cellar"),
        shot(src="c.mp4", location="Kitchen"),
        shot(src="d.mp4", location="Kitchen"),
    ])
    assert len(groups) == 2
    assert {len(g) for g in groups} == {2}


def test_a_lone_shot_cannot_contradict_anything():
    # Continuity is a comparison. One shot of a location is not a group.
    groups = group_for_comparison([shot(location="Cellar"), shot(location="Kitchen")])
    assert groups == []


def test_shots_with_no_continuity_text_are_excluded():
    # Rows logged before the continuity field existed carry an empty string;
    # feeding them in would invite the model to invent a contradiction.
    groups = group_for_comparison([
        shot(src="a.mp4"), shot(src="b.mp4", continuity=""),
        shot(src="c.mp4", continuity="   "),
    ])
    assert groups == []


def test_the_prompt_carries_each_shot_label_and_its_state():
    client = FakeClient("[]")
    group = [shot(src="a.mp4", start=1.0, continuity="lamp lit"),
             shot(src="b.mp4", start=2.0, continuity="lamp unlit")]
    check_group(group, client, model="test-model")

    prompt = next(p["text"] for p in client.models.calls[0]["contents"] if "text" in p)
    assert "lamp lit" in prompt and "lamp unlit" in prompt
    assert shot_label(group[0]) in prompt and shot_label(group[1]) in prompt


def test_findings_naming_a_shot_that_was_not_in_the_group_are_rejected():
    # The model can invent a plausible-looking clip name. A continuity report
    # pointing an editor at a shot that was never compared is worse than none.
    group = [shot(src="a.mp4"), shot(src="b.mp4", start=5.0)]
    reply = json.dumps([{"subject": "Ben", "detail": "jacket changes",
                         "shots": ["a.mp4 @0.0s", "ZZZ_invented.mp4 @9.9s"]}])
    with pytest.raises(ValueError, match="not in this group"):
        check_group(group, FakeClient(reply))


def test_a_clean_group_reports_nothing():
    group = [shot(src="a.mp4"), shot(src="b.mp4", start=5.0)]
    assert check_group(group, FakeClient("[]")) == []


def test_a_real_finding_comes_back_with_its_shots():
    group = [shot(src="a.mp4"), shot(src="b.mp4", start=5.0)]
    reply = json.dumps([{"subject": "Ben", "detail": "rifle switches hands",
                         "shots": [shot_label(group[0]), shot_label(group[1])]}])
    (finding,) = check_group(group, FakeClient(reply))
    assert finding["subject"] == "Ben"
    assert "rifle" in finding["detail"]


class FakeModels:
    def __init__(self, text):
        self._text, self.calls = text, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"text": self._text})()


class FakeClient:
    def __init__(self, text):
        self.models = FakeModels(text)
