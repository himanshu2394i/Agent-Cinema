"""The evidence ledger: what the agent has checked, and what it still owes."""

import copy

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


def test_ranked_clips_carry_a_ready_made_watch_url():
    """The model must copy the link, not retype the host.

    Asked to build the URL from a base in its prompt, the model intermittently
    dropped a digit ('127.00.1') - and when it slipped, every link in that
    answer was broken.
    """
    from dailies_agent.editorial_tools import _with_watch_urls

    clips = [{"clip": "A001_C0063.mp4"}, {"clip": "A001_C0123.mp4"}]
    out = _with_watch_urls(clips, "lailamajnu", "http://127.0.0.1:8080/")
    assert out[0]["watch_url"] == (
        "http://127.0.0.1:8080/watch?project=lailamajnu&file=A001_C0063.mp4"
    )
    assert out[1]["watch_url"].endswith("file=A001_C0123.mp4")


def test_sequence_clips_come_back_as_finished_markdown_links():
    """Pairing filenames against a parallel URL list is where links still broke.

    A sequence lists several clips, so the model had to match name to URL by
    position. Handing it the finished link removes the pairing step.
    """
    from dailies_agent.editorial_tools import _sequence_links

    sequence = {"clips": ["A001_C0056.mp4", "A001_C0057.mp4"]}
    _sequence_links(sequence, "lailamajnu", "http://127.0.0.1:8080")
    assert sequence["clip_links"] == [
        "[A001_C0056.mp4](http://127.0.0.1:8080/watch?project=lailamajnu&file=A001_C0056.mp4)",
        "[A001_C0057.mp4](http://127.0.0.1:8080/watch?project=lailamajnu&file=A001_C0057.mp4)",
    ]


def test_select_list_display_carries_the_link_not_a_bare_filename(monkeypatch, tmp_path):
    """The last dead links came from here: display gave a name, no address."""
    import projects
    import dailies_agent.editorial_tools as tools

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    ctx = _FakeCtx()
    tools.add_to_select_list(
        [{
            "clip": "A001_C0123.mp4", "best_take": 6, "score": 0.8,
            "confidence": "moderate", "selection_reason": "embrace",
        }],
        tool_context=ctx,
    )
    line = tools.get_select_list(tool_context=ctx)["display"][0]
    assert line.startswith(
        "[A001_C0123.mp4](http://127.0.0.1:8080/watch?project=lailamajnu"
        "&file=A001_C0123.mp4)"
    )
    assert "take 6" in line and "moderate" in line and "embrace" in line


def test_trace_rows_show_actions_and_evidence_not_reasoning():
    from dailies_agent.investigation import trace_rows

    ledger = []
    record(ledger, tool="investigate_scene", question="talks to father",
           clips_seen=["C0100", "C0109"], finding="anchor C0100-C0100.",
           evidence_tier="DIRECT_INTERACTION", invocation="t1")
    record(ledger, tool="inspect_clips", question="What is on C0101-C0103?",
           clips_seen=["C0101", "C0102", "C0103"],
           finding="3 clips with footage.", invocation="t1")
    rows = trace_rows(ledger)
    assert [r["step"] for r in rows] == [1, 2]
    assert rows[0]["label"] == "Mapped the sequence"
    assert rows[1]["label"] == "Inspected the footage"
    # Clip ranges collapse so a long list stays readable.
    assert rows[1]["clips"] == "C0101-C0103"
    assert rows[0]["clips"] == "C0100, C0109"
    assert rows[1]["finding"] == "3 clips with footage."
    assert "reasoning" not in rows[0] and "thought" not in rows[0]


def test_trace_rows_scope_to_one_turn_when_asked():
    from dailies_agent.investigation import trace_rows

    ledger = []
    record(ledger, tool="rank_clips", question="old", clips_seen=["C0063"],
           finding="ranked", invocation="t1")
    record(ledger, tool="inspect_clips", question="new", clips_seen=["C0101"],
           finding="looked", invocation="t2")
    rows = trace_rows(ledger, invocation="t2")
    assert len(rows) == 1
    assert rows[0]["step"] == 1, "steps renumber within the turn"


def test_trace_rows_survive_an_unknown_tool():
    from dailies_agent.investigation import trace_rows

    ledger = []
    record(ledger, tool="some_new_tool", question="q", clips_seen=[],
           finding="f", invocation="t1")
    assert trace_rows(ledger)[0]["label"] == "some_new_tool"


class _AdkLikeState(dict):
    """ADK's State persists what is assigned, not what is mutated in place.

    A list appended to without reassignment never reaches the session store,
    so steps after the first turn silently vanished.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.persisted = {}

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        # Snapshot, the way a session store serializes it - so a list that is
        # only mutated in place afterwards does not update what was stored.
        self.persisted[key] = copy.deepcopy(value)


def test_each_recorded_step_is_written_back_to_session_state():
    import dailies_agent.editorial_tools as tools

    ctx = _FakeCtx()
    ctx.state = _AdkLikeState({"project_id": "lailamajnu"})
    tools._note(ctx, tool="rank_clips", question="q1", clips_seen=["C0063"],
                finding="first turn")
    ctx.invocation_id = "turn-2"
    tools._note(ctx, tool="inspect_clips", question="q2", clips_seen=["C0101"],
                finding="second turn")
    assert len(ctx.state.persisted["investigation"]) == 2, (
        "the second step must be assigned back, not just appended"
    )
