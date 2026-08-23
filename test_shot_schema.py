import re

from shot_schema import (
    DB_ONLY_COLUMNS, MODEL_FIELDS, clickhouse_ddl, shot_response_schema,
)
from vocab import CRAFT_VOCAB, ProjectVocabulary

VOCAB = ProjectVocabulary.from_raw(
    characters=["SARAH", "DET. RUIZ"],
    locations=["DINER", "SARAH'S CAR"],
    props=["the letter"],
    scenes=["1", "14B"],
)


def _props(schema):
    return schema["items"]["properties"]


def test_response_is_a_list_of_shots():
    # One clip contains many shots; Gemini segments and logs in one pass.
    schema = shot_response_schema(VOCAB)
    assert schema["type"] == "array"
    assert schema["items"]["type"] == "object"


def test_craft_enums_come_from_the_fixed_vocabulary():
    p = _props(shot_response_schema(VOCAB))
    assert p["shot_size"]["enum"] == CRAFT_VOCAB["shot_size"]
    assert p["camera_movement"]["enum"] == CRAFT_VOCAB["camera_movement"]
    assert p["int_ext"]["enum"] == CRAFT_VOCAB["int_ext"]


def test_project_enums_come_from_the_screenplay_and_allow_unknown():
    p = _props(shot_response_schema(VOCAB))
    assert p["location"]["enum"] == ["Diner", "Sarah's Car", "unknown"]
    assert p["characters"]["items"]["enum"] == ["Sarah", "Det. Ruiz", "unknown"]
    assert p["scene"]["enum"] == ["1", "14B", "unknown"]


def test_open_text_fields_have_no_enum():
    p = _props(shot_response_schema(VOCAB))
    for name in ("dialogue", "action"):
        assert p[name]["type"] == "string"
        assert "enum" not in p[name], f"{name} must stay free text"


def test_every_model_field_is_required():
    schema = shot_response_schema(VOCAB)
    assert set(schema["items"]["required"]) == {f.name for f in MODEL_FIELDS}


def test_ddl_and_response_schema_describe_the_same_fields():
    # The anti-drift guarantee. If these ever disagree, ingest writes columns
    # the agent cannot filter on, and queries silently return nothing.
    schema_fields = set(_props(shot_response_schema(VOCAB)))
    ddl = clickhouse_ddl("shots")
    ddl_columns = set(re.findall(r"^\s{4}(\w+)\s", ddl, re.MULTILINE))
    assert ddl_columns - DB_ONLY_COLUMNS == schema_fields


def test_enum_columns_use_low_cardinality():
    ddl = clickhouse_ddl("shots")
    assert re.search(r"shot_size\s+LowCardinality\(String\)", ddl)
    assert re.search(r"characters\s+Array\(LowCardinality\(String\)\)", ddl)
    # Free text must not be LowCardinality - every value is distinct.
    assert re.search(r"dialogue\s+String", ddl)
    assert not re.search(r"dialogue\s+LowCardinality", ddl)


def test_ddl_is_a_mergetree_ordered_for_the_common_query():
    ddl = clickhouse_ddl("shots")
    assert "ENGINE = MergeTree" in ddl
    assert "ORDER BY (scene, take, start_seconds)" in ddl
    assert ddl.startswith("CREATE TABLE IF NOT EXISTS shots")


def test_agent_instruction_lists_the_same_vocabulary_ingest_writes():
    from shot_schema import agent_instruction

    text = agent_instruction(VOCAB)
    # Read side must know every closed value the write side can produce.
    for value in CRAFT_VOCAB["time_of_day"] + ["Sarah", "Det. Ruiz", "unknown"]:
        assert repr(value) in text, value
    # Free text is described, not enumerated.
    assert "action: String, free text" in text
    # The empty-result protocol is the whole point of the agent.
    assert "ILIKE" in text and "no footage" in text


def test_agent_instruction_explains_the_two_populations():
    # Real logged footage (A001_C0001.mp4, scene='unknown') and synthetic
    # filler (gs://..., scene='P07-14B') share the table. Without this the
    # agent treats scene-id filters as valid for real footage and vice versa.
    from shot_schema import agent_instruction

    text = agent_instruction(VOCAB)
    assert "A001_C0001.mp4" in text
    assert "scene" in text and "unknown" in text
    assert "synthetic" in text.lower()


def test_high_cardinality_fields_are_not_enumerated_in_full():
    from shot_schema import MAX_ENUMERATED, agent_instruction
    from vocab import ProjectVocabulary

    big = ProjectVocabulary.from_raw(
        characters=["Sarah"], locations=[], props=[],
        scenes=[f"P{p:02d}-{n}" for p in range(1, 20) for n in range(1, 40)],
    )
    text = agent_instruction(big)
    assert "SELECT DISTINCT scene" in text
    assert text.count("'P01-") <= MAX_ENUMERATED
    # Small vocabularies stay fully listed - that is the common case.
    assert "'Sarah'" in text and "DISTINCT characters" not in text


def test_source_file_description_covers_both_populations():
    # It used to say "the gs:// clip this shot came from", which contradicted
    # the population note in the same prompt and described only the synthetic
    # rows - the real footage is named like a camera roll.
    from shot_schema import agent_instruction

    text = agent_instruction(VOCAB)
    assert "the gs:// clip this shot came from" not in text
    line = next(l for l in text.splitlines() if l.strip().startswith("source_file:"))
    assert "gs://" not in line, f"source_file described as gs:// only: {line!r}"
