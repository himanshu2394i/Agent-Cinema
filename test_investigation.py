"""The evidence ledger: what the agent has checked, and what it still owes."""

from dailies_agent.investigation import (
    MAX_INVESTIGATION_STEPS,
    clip_label,
    record,
    review,
)


def test_record_stores_an_observable_step_not_reasoning():
    ledger = []
    step = record(
        ledger,
        tool="inspect_clips",
        question="What occurs immediately after C0100?",
        clips_seen=["C0101", "C0102"],
        finding="C0101 continues the father confrontation.",
        evidence_tier="DIRECT_INTERACTION",
    )
    assert step["step"] == 1
    assert step["tool"] == "inspect_clips"
    assert step["clips_seen"] == ["C0101", "C0102"]
    assert step["evidence_tier"] == "DIRECT_INTERACTION"
    assert ledger == [step]
    assert record(ledger, tool="rank_clips", question="q", clips_seen=[], finding="f")["step"] == 2


def test_empty_ledger_is_sufficient_with_full_budget():
    verdict = review([])
    assert verdict["sufficient"] is True
    assert verdict["remaining_budget"] == MAX_INVESTIGATION_STEPS
    assert verdict["gap"] is None


def test_unchecked_chronological_followup_is_a_named_gap():
    ledger = []
    record(
        ledger,
        tool="investigate_scene",
        question="What happens after Qays talks to Laila's father?",
        clips_seen=["C0100", "C0109"],
        finding="anchor C0100",
        pending_followup=[101, 104],
    )
    verdict = review(ledger)
    assert verdict["sufficient"] is False
    assert verdict["gap"] == "chronological_followup_unchecked"
    assert verdict["recommended_action"] == "inspect_clips"
    # It must name the clips it has not looked at, not just complain.
    assert verdict["missing_clips"] == ["C0101", "C0102", "C0103", "C0104"]


def test_gap_closes_once_those_clips_are_inspected():
    ledger = []
    record(ledger, tool="investigate_scene", question="after?", clips_seen=["C0100"],
           finding="anchor C0100", pending_followup=[101, 102])
    record(ledger, tool="inspect_clips", question="C0101-C0102?",
           clips_seen=["C0101", "C0102"], finding="C0101 continues it.")
    verdict = review(ledger)
    assert verdict["sufficient"] is True
    assert verdict["gap"] is None


def test_exhausted_budget_stops_investigating_and_answers_honestly():
    ledger = []
    record(ledger, tool="investigate_scene", question="after?", clips_seen=["C0100"],
           finding="anchor", pending_followup=[101, 102])
    for n in range(MAX_INVESTIGATION_STEPS - 1):
        record(ledger, tool="rank_clips", question=f"q{n}", clips_seen=[], finding="f")
    verdict = review(ledger)
    assert verdict["remaining_budget"] == 0
    assert verdict["budget_exhausted"] is True
    assert verdict["recommended_action"] == "answer_with_uncertainty"


def test_clip_label_is_roll_agnostic():
    assert clip_label(101) == "C0101"
    assert clip_label("A001_C0101.mp4") == "C0101"
    assert clip_label("gs://bucket/synthetic.mp4") is None


def _report(anchor_end, next_start, sequence_count=6):
    return {
        "sequence_count": sequence_count,
        "sequences": [{"start_clip": anchor_end}],
        "anchor": {"scene_id": f"C{anchor_end:04d}", "end_clip": anchor_end,
                   "evidence_tier": "DIRECT_INTERACTION"},
        "after": {"scene_id": f"C{next_start:04d}", "start_clip": next_start},
    }


def test_targeted_followup_over_a_gap_owes_the_skipped_clips():
    from dailies_agent.editorial_tools import _scene_step

    step = _scene_step(_report(100, 109), ["Qays"], "talks to father", [])
    # C0101-C0108 were never looked at; neighbor_range bounds the debt to 3.
    assert step["pending_followup"] == [101, 103]


def test_adjacent_next_sequence_owes_nothing():
    from dailies_agent.editorial_tools import _scene_step

    step = _scene_step(_report(100, 101), ["Qays"], "talks to father", [])
    assert "pending_followup" not in step


def test_broad_listing_makes_no_followup_claim_so_owes_nothing():
    from dailies_agent.editorial_tools import _scene_step

    step = _scene_step(_report(100, 109), ["Laila", "Qays"], None, [])
    assert "pending_followup" not in step


def test_budget_is_per_question_not_per_session():
    """A long session must not leave later questions with no budget."""
    ledger = []
    for n in range(MAX_INVESTIGATION_STEPS):
        record(ledger, tool="rank_clips", question=f"old {n}", clips_seen=[],
               finding="f", invocation="turn-1")
    record(ledger, tool="investigate_scene", question="new question",
           clips_seen=["C0100"], finding="anchor", invocation="turn-2")
    verdict = review(ledger, invocation="turn-2")
    assert verdict["remaining_budget"] == MAX_INVESTIGATION_STEPS - 1
    assert verdict["budget_exhausted"] is False
    # The whole ledger stays readable for the trace, but only this turn counts.
    assert verdict["step_count"] == 1
    assert len(verdict["steps"]) == 1


def test_a_previous_turns_debt_does_not_block_this_one():
    ledger = []
    record(ledger, tool="investigate_scene", question="old", clips_seen=["C0100"],
           finding="anchor", pending_followup=[101, 103], invocation="turn-1")
    record(ledger, tool="rank_clips", question="new", clips_seen=["C0063"],
           finding="ranked", invocation="turn-2")
    assert review(ledger, invocation="turn-2")["sufficient"] is True
    assert review(ledger, invocation="turn-1")["sufficient"] is False


class _FakeCtx:
    """ToolContext stand-in: tools only need .state and .invocation_id."""

    def __init__(self):
        self.state = {"project_id": "lailamajnu"}
        self.invocation_id = "turn-1"


def test_investigate_scene_closes_its_own_chronological_gap(monkeypatch):
    """The tool must not depend on the model choosing to iterate.

    A targeted 'what happens after' question whose next match skips footage
    gets that footage fetched here, so the model cannot answer without it.
    """
    import dailies_agent.editorial_tools as tools

    def fake_rows(_client, _project, _criteria, **kwargs):
        if kwargs.get("clip_numbers") == [101, 102, 103]:
            return [{"source_file": f"A001_C0{n}.mp4", "take": 1,
                     "characters": ["Laila"], "time_of_day": "night",
                     "location": "House", "scene": "unknown",
                     "action": "Laila looks down, pensive.",
                     "dialogue": "", "continuity": ""} for n in (101, 102, 103)]
        return [{"source_file": f"A001_C0{n}.mp4", "take": 1,
                 "characters": ["Qays", "Laila's Father"], "time_of_day": "night",
                 "location": "House", "scene": "unknown",
                 "action": "Qays talks to Laila's Father",
                 "dialogue": "", "continuity": ""} for n in (100, 109)]

    monkeypatch.setattr(tools, "_project", lambda ctx: "lailamajnu")
    monkeypatch.setitem(__import__("sys").modules, "dailies_agent.db_connect",
                        type("M", (), {"connect": staticmethod(lambda: None)}))
    monkeypatch.setattr("dailies_agent.editorial.fetch_matching_shots", fake_rows)

    ctx = _FakeCtx()
    report = tools.investigate_scene(
        characters=["Qays", "Laila's Father"],
        event="talks to father",
        tool_context=ctx,
    )
    following = report["immediately_after"]
    assert following["range"] == "C0101-C0103"
    assert [c["clip_label"] for c in following["clips"]] == ["C0101", "C0102", "C0103"]
    # Having fetched it, the tool owes nothing: one call is enough to answer.
    assert review(ctx.state["investigation"], invocation="turn-1")["sufficient"] is True
