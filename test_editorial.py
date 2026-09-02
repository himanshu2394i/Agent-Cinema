"""Deterministic clip ranking for the query agent."""

import pytest

from dailies_agent.editorial import (
    RankingProfile,
    SearchCriteria,
    build_clip_summary,
    rank_takes,
    score_take,
    summarize_clip_takes,
)


def _shot(
    source_file="A001_C0001.mp4",
    take=1,
    *,
    characters=None,
    time_of_day="day",
    action="",
    dialogue="",
    shot_size="medium",
    quality_flags=None,
    start_seconds=0.0,
    end_seconds=5.0,
):
    return {
        "source_file": source_file,
        "take": take,
        "characters": characters or [],
        "time_of_day": time_of_day,
        "action": action,
        "dialogue": dialogue,
        "shot_size": shot_size,
        "quality_flags": quality_flags or ["none"],
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
    }


def test_score_take_rewards_named_characters_over_unknown():
    criteria = SearchCriteria(characters=["Laila", "Qays"], keywords=["crying"])
    emotional = _shot(
        take=1,
        characters=["Laila", "Qays"],
        time_of_day="night",
        action="Laila cries in Qays's arms",
    )
    generic = _shot(
        take=2,
        characters=["unknown"],
        time_of_day="night",
        action="a woman cries with a man",
    )
    assert score_take(emotional, criteria, RankingProfile.EMOTIONAL) > score_take(
        generic, criteria, RankingProfile.EMOTIONAL
    )


def test_ranking_profile_changes_weights():
    criteria = SearchCriteria(characters=["Laila"], keywords=["marry"])
    dialogue_take = _shot(
        take=1,
        characters=["Laila"],
        dialogue="I want to marry you",
        action="she speaks softly",
    )
    visual_take = _shot(
        take=2,
        characters=["Laila"],
        dialogue="",
        action="she smiles while talking about marriage",
    )
    assert score_take(dialogue_take, criteria, RankingProfile.DIALOGUE) > score_take(
        visual_take, criteria, RankingProfile.DIALOGUE
    )


def test_summarize_clip_takes_groups_and_picks_best():
    criteria = SearchCriteria(time_of_day=["night"])
    rows = [
        _shot(source_file="A001_C0037.mp4", take=6, time_of_day="night", action="car at night"),
        _shot(source_file="A001_C0037.mp4", take=7, time_of_day="night", action="car at night, clearer"),
        _shot(source_file="A001_C0037.mp4", take=8, time_of_day="night", quality_flags=["soft_focus"]),
        _shot(source_file="A001_C0040.mp4", take=1, time_of_day="night", action="house exterior"),
    ]
    summaries = summarize_clip_takes(rows, criteria, RankingProfile.BALANCED)
    by_clip = {s["clip"]: s for s in summaries}
    assert by_clip["A001_C0037.mp4"]["matching_takes"] == [6, 7, 8]
    assert by_clip["A001_C0037.mp4"]["best_take"] in {6, 7, 8}
    assert by_clip["A001_C0040.mp4"]["matching_takes"] == [1]


def test_duplicate_take_numbers_keep_the_higher_score():
    criteria = SearchCriteria(time_of_day=["night"])
    rows = [
        _shot(source_file="A001_C0063.mp4", take=1, time_of_day="night", action="crying under a tree"),
        _shot(source_file="A001_C0063.mp4", take=1, time_of_day="night", action="they sit quietly"),
    ]
    summaries = summarize_clip_takes(rows, criteria, RankingProfile.EMOTIONAL)
    assert summaries[0]["matching_takes"] == [1]
    assert summaries[0]["best_take"] == 1


def test_rank_takes_returns_top_clips_with_evidence():
    criteria = SearchCriteria(
        characters=["Laila", "Qays"],
        time_of_day=["night"],
        keywords=["crying"],
    )
    rows = [
        _shot(
            source_file="A001_C0123.mp4",
            take=7,
            characters=["Laila", "Qays"],
            time_of_day="night",
            action="Qays holds Laila while she is crying",
            dialogue="Main kya karu Qays",
        ),
        _shot(
            source_file="A001_C0123.mp4",
            take=6,
            characters=["Laila", "Qays"],
            time_of_day="night",
            action="they embrace",
        ),
        _shot(
            source_file="A001_C0099.mp4",
            take=1,
            characters=["unknown"],
            time_of_day="night",
            action="dark street",
        ),
    ]
    ranked = rank_takes(rows, criteria, RankingProfile.EMOTIONAL, limit=2)
    assert ranked[0]["clip"] == "A001_C0123.mp4"
    assert ranked[0]["best_take"] == 7
    assert ranked[0]["score"] > ranked[1]["score"]
    assert "Qays" in ranked[0]["evidence"]["characters"]
    assert ranked[0]["alternatives"]


def _ctx(project_id="lailamajnu"):
    return type("Ctx", (), {"state": {"project_id": project_id}})()


def test_add_to_select_list_keeps_an_editorial_record(monkeypatch, tmp_path):
    import projects
    from dailies_agent.editorial_tools import add_to_select_list, get_select_list

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    ctx = _ctx()
    result = add_to_select_list(
        [
            {
                "clip": "A001_C0123.mp4",
                "best_take": 7,
                "score": 0.94,
                "confidence": "high",
                "evidence": {
                    "action": "Qays holds Laila while she is crying",
                    "characters": ["Qays", "Laila"],
                },
            }
        ],
        tool_context=ctx,
    )
    entry = result["added"][0]
    assert entry["clip"] == "A001_C0123.mp4"
    assert entry["best_take"] == 7
    assert entry["ranking_score"] == 0.94
    assert entry["confidence"] == "high"
    assert "crying" in entry["selection_reason"]
    assert get_select_list(ctx)["count"] == 1


def test_select_list_survives_a_fresh_session(monkeypatch, tmp_path):
    """A select list only readable in the same session is not a record of
    anything - it must be readable from a brand-new session/state dict."""
    import projects
    from dailies_agent.editorial_tools import add_to_select_list, get_select_list

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    add_to_select_list(
        [{"clip": "A001_C0123.mp4", "best_take": 7, "score": 0.9,
          "confidence": "high", "selection_reason": "the take"}],
        tool_context=_ctx(),
    )
    fresh_session = _ctx()
    result = get_select_list(fresh_session)
    assert result["count"] == 1
    assert result["select_list"][0]["clip"] == "A001_C0123.mp4"


def test_add_to_select_list_replaces_duplicate_clip_and_take(monkeypatch, tmp_path):
    """Re-adding the same clip+take updates the row instead of duplicating it."""
    import projects
    from dailies_agent.editorial_tools import add_to_select_list, get_select_list

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    ctx = _ctx()
    add_to_select_list(
        [{"clip": "A001_C0123.mp4", "best_take": 7, "score": 0.8,
          "confidence": "moderate", "selection_reason": "first pass"}],
        tool_context=ctx,
    )
    add_to_select_list(
        [{"clip": "A001_C0123.mp4", "best_take": 7, "score": 0.95,
          "confidence": "high", "selection_reason": "updated pick"}],
        tool_context=ctx,
    )
    result = get_select_list(ctx)
    assert result["count"] == 1
    assert result["select_list"][0]["selection_reason"] == "updated pick"
    assert result["select_list"][0]["ranking_score"] == 0.95


def test_get_select_list_missing_file_is_an_empty_list(monkeypatch, tmp_path):
    import projects
    from dailies_agent.editorial_tools import get_select_list

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    result = get_select_list(_ctx())
    assert result == {"select_list": [], "count": 0, "display": []}


def test_get_select_list_corrupt_file_reports_instead_of_raising(monkeypatch, tmp_path):
    import projects
    from dailies_agent.editorial_tools import get_select_list

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    selects_path = projects.project_dir("lailamajnu") / "selects.json"
    selects_path.parent.mkdir(parents=True)
    selects_path.write_text("{not valid json")

    result = get_select_list(_ctx())
    assert result["count"] == 0
    assert result["select_list"] == []
    assert "error" in result


def test_critique_ranking_flags_the_weakest_conflict():
    from dailies_agent.editorial import critique_ranking

    clips = [
        {
            "clip": "A001_C0063.mp4",
            "best_take": 1,
            "score": 0.85,
            "confidence": "high",
            "evidence": {
                "action": "the woman is visibly upset and crying, speaking to the man",
                "characters": ["Laila", "Qays"],
            },
        },
        {
            "clip": "A001_C0123.mp4",
            "best_take": 6,
            "score": 0.80,
            "confidence": "moderate",
            "evidence": {
                "action": "Qays embraces Laila, who is crying intensely",
                "characters": ["Qays", "Laila"],
            },
        },
        {
            "clip": "A001_C0124.mp4",
            "best_take": 1,
            "score": 0.80,
            "confidence": "moderate",
            "evidence": {
                "action": "A man laughs loudly and speaks to the crying woman",
                "characters": ["Qays", "Laila"],
            },
        },
    ]
    note = critique_ranking(clips)
    assert note["do_not_increase_confidence"] is True
    assert note["strongest"]["clip"] == "A001_C0063.mp4"
    assert note["strong_alternative"]["clip"] == "A001_C0123.mp4"
    assert note["weakest"]["clip"] == "A001_C0124.mp4"
    assert "laugh" in note["weakness"].casefold()
    assert "Not completely" in note["challenge_answer"]
    # challenge_answer is read out to the editor, so it must not carry
    # instructions aimed at the model. The boolean flag carries that.
    assert "Do not raise confidence" not in note["challenge_answer"]
    assert note["challenge_answer"].rstrip().endswith(".")


def test_build_clip_summary_includes_confidence_band():
    summary = build_clip_summary(
        clip="A001_C0123.mp4",
        ranked_takes=[
            {"take": 7, "score": 0.94, "evidence": {"action": "crying"}},
            {"take": 6, "score": 0.89, "evidence": {"action": "embrace"}},
        ],
    )
    assert summary["best_take"] == 7
    assert summary["confidence"] in {"high", "moderate", "low"}
