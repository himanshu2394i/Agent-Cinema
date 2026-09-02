"""Scene-level grouping of consecutive camera clips."""

from dailies_agent.scene import (
    chronological_coverage,
    clip_index,
    group_consecutive_clips,
    investigate_from_rows,
    neighbor_range,
    summarize_sequence,
)


def _row(file, take=1, characters=None, action="", dialogue="", continuity=""):
    return {
        "source_file": file,
        "take": take,
        "characters": characters or ["Laila", "Qays"],
        "time_of_day": "night",
        "location": "Garden",
        "scene": "unknown",
        "action": action,
        "dialogue": dialogue,
        "continuity": continuity,
    }


def test_clip_index_reads_camera_roll_number():
    assert clip_index("A001_C0064.mp4") == 64
    assert clip_index("A001_C0001.mp4") == 1
    assert clip_index("gs://dailies/A004_C0834.mp4") is None


def test_consecutive_clips_form_one_sequence():
    rows = [
        _row("A001_C0064.mp4", action="they sit under a tree"),
        _row("A001_C0065.mp4", action="Qays speaks urgently"),
        _row("A001_C0066.mp4", action="Laila looks away"),
        _row("A001_C0122.mp4", action="Qays waits"),
        _row("A001_C0123.mp4", action="they embrace"),
    ]
    sequences = group_consecutive_clips(rows, max_gap=1)
    assert len(sequences) == 2
    assert [c["clip"] for c in sequences[0]["clips"]] == [
        "A001_C0064.mp4",
        "A001_C0065.mp4",
        "A001_C0066.mp4",
    ]
    assert sequences[0]["scene_id"] == "C0064-C0066"
    assert sequences[1]["scene_id"] == "C0122-C0123"


def test_gap_breaks_a_sequence():
    rows = [
        _row("A001_C0001.mp4"),
        _row("A001_C0004.mp4"),
    ]
    sequences = group_consecutive_clips(rows, max_gap=1)
    assert len(sequences) == 2


def test_summarize_sequence_has_editorial_fields():
    rows = [
        _row("A001_C0064.mp4", action="under the tree", dialogue="Chal bhag jaayein"),
        _row("A001_C0065.mp4", action="Laila is crying", dialogue="Nahi"),
        _row("A001_C0065.mp4", take=2, action="Laila is crying harder"),
    ]
    grouped = group_consecutive_clips(rows, max_gap=1)
    summary = summarize_sequence(grouped[0])
    assert summary["scene_id"] == "C0064-C0065"
    assert summary["clip_count"] == 2
    assert "Laila" in summary["characters"]
    assert summary["dialogue_summary"]
    assert "crying" in summary["emotional_arc"].casefold()
    assert summary["confidence"] in {"high", "moderate", "low"}


def test_after_is_next_on_the_timeline_not_keyword_sorted():
    """C0100 must never be followed by an earlier clip such as C0067."""
    rows = [
        _row("A001_C0067.mp4", action="Qays and Laila hold hands"),
        _row("A001_C0100.mp4", action="Qays talks to Laila's father"),
        _row("A001_C0101.mp4", action="Father listens, Qays gestures"),
    ]
    report = investigate_from_rows(rows, event="father")
    anchor = report["anchor"]
    assert anchor["scene_id"] in {"C0100-C0100", "C0100-C0101"}
    after = report.get("after")
    if after:
        assert (after.get("start_clip") or 0) > (anchor.get("end_clip") or 0)
        assert "C0067" not in after["clips"][0]
    # C0067 is earlier on the roll — must never be chosen as "after"
    assert after is None or "C0067" not in str(after.get("scene_id", ""))


def test_metadata_only_sequence_is_tiered_not_treated_as_interaction():
    rows = [
        _row(
            "A001_C0004.mp4",
            action="A motorcycle with two men drives past two police officers.",
        ),
        _row(
            "A001_C0049.mp4",
            action="Laila listens to Qays. Qays smiles.",
            dialogue="Par chhodunga nahi main",
        ),
    ]
    report = investigate_from_rows(rows, characters=["Laila", "Qays"])
    by_id = {s["scene_id"]: s for s in report["sequences"]}
    assert by_id["C0004-C0004"]["evidence_tier"] == "METADATA_ONLY"
    assert by_id["C0049-C0049"]["evidence_tier"] == "DIRECT_INTERACTION"
    # Story order, not relevance order: the tier is what marks C0004 weak,
    # not its position in the list.
    assert report["sequences"][0]["scene_id"] == "C0004-C0004"


def test_investigate_after_follows_timeline_for_event():
    rows = [
        _row("A001_C0070.mp4", action="Qays talks to Laila's father"),
        _row("A001_C0071.mp4", action="Father refuses"),
        _row("A001_C0122.mp4", action="Qays waits under the tree"),
    ]
    report = investigate_from_rows(rows, event="father")
    assert report["sequences"][0]["scene_id"] == "C0070-C0071"
    after = report["after"]
    assert after["scene_id"] == "C0122-C0122"
    assert "waits" in after["actions"][0]


def test_neighbor_range_is_the_next_clip_numbers():
    assert neighbor_range(71, 3) == (72, 74)


def test_chronological_coverage_lists_every_clip_in_order_with_gaps_named():
    rows = [
        _row("A001_C0103.mp4", characters=["Villagers"], action="A crowd disperses"),
        _row("A001_C0101.mp4", action="Laila's Father releases Qays; Laila pulls him back"),
    ]
    report = chronological_coverage(rows, 101, 104, wanted_characters=["Qays", "Laila"])
    # Literal coverage order, never relevance order.
    assert [c["clip_label"] for c in report["clips"]] == ["C0101", "C0103"]
    assert report["clips"][0]["evidence_tier"] == "DIRECT_INTERACTION"
    assert report["clips"][1]["evidence_tier"] == "METADATA_ONLY"
    # Clips with no footage in the archive are reported, not silently dropped.
    assert report["missing_clips"] == ["C0102", "C0104"]
    assert report["range"] == "C0101-C0104"


def test_sequences_come_back_in_story_order_not_relevance_order():
    """'Everything between X and Y' is a story, so it reads front to back.

    Tier still decides what makes the cut when there are more sequences than
    room, and stays on each item so the agent can flag weak evidence.
    """
    rows = [
        # Metadata-only: the pair is tagged but the prose shows neither.
        _row("A001_C0004.mp4", action="A motorcycle drives past two police officers"),
        _row("A001_C0063.mp4", action="Laila cries as Qays sits beside her"),
        _row("A001_C0100.mp4", action="Qays talks; Laila looks down"),
    ]
    report = investigate_from_rows(rows, characters=["Laila", "Qays"])
    labels = [s["start_clip"] for s in report["sequences"]]
    assert labels == sorted(labels), "sequences must read in shooting order"
    tiers = {s["start_clip"]: s["evidence_tier"] for s in report["sequences"]}
    assert tiers[4] == "METADATA_ONLY"
    assert tiers[63] == "DIRECT_INTERACTION"


def test_weak_evidence_is_dropped_first_when_there_is_no_room():
    rows = [
        _row("A001_C0004.mp4", action="A motorcycle drives past two police officers"),
        _row("A001_C0063.mp4", action="Laila cries as Qays sits beside her"),
    ]
    report = investigate_from_rows(rows, characters=["Laila", "Qays"], max_sequences=1)
    assert [s["start_clip"] for s in report["sequences"]] == [63]
