import json
from collections import defaultdict

from ingest import rows_from_response
from shot_schema import MODEL_FIELDS
from synth import generate_rows
from vocab import ProjectVocabulary

VOCAB = ProjectVocabulary.from_raw(
    characters=["SARAH", "DET. RUIZ", "MARCUS"],
    locations=["DINER", "PRECINCT", "SARAH'S CAR"],
    props=["the letter", "badge"],
    scenes=["1", "2", "14B", "22"],
)


def rows(count=200, seed=0):
    return list(generate_rows(VOCAB, count, seed=seed))


def test_yields_exactly_the_requested_count():
    assert len(rows(137)) == 137


def test_rows_match_the_schema_field_set():
    expected = {f.name for f in MODEL_FIELDS} | {"source_file", "project_id"}
    assert all(set(r) == expected for r in rows(50))


def test_same_seed_reproduces_the_same_data():
    assert rows(80, seed=7) == rows(80, seed=7)


def test_different_seeds_differ():
    assert rows(80, seed=7) != rows(80, seed=8)


def test_a_scene_keeps_one_location_and_one_int_ext():
    # A shoot does not teleport between takes of the same scene.
    by_scene = defaultdict(set)
    for r in rows(500):
        by_scene[r["scene"]].add((r["location"], r["int_ext"], r["time_of_day"]))
    assert all(len(v) == 1 for v in by_scene.values())


def test_takes_are_numbered_from_one_within_a_scene():
    # "14B" is scene 14, setup B. Takes run 1..n inside it, even if the
    # generator returns to that setup later in the shoot.
    by_scene = defaultdict(list)
    for r in rows(400):
        by_scene[r["scene"]].append(r["take"])
    for takes in by_scene.values():
        assert takes == list(range(1, len(takes) + 1))


def test_a_setup_keeps_one_framing():
    by_scene = defaultdict(set)
    for r in rows(400):
        by_scene[r["scene"]].add((r["shot_size"], r["camera_movement"]))
    assert all(len(v) == 1 for v in by_scene.values())


def test_each_take_is_its_own_clip_file():
    files = [r["source_file"] for r in rows(300)]
    assert len(set(files)) == len(files)


def test_most_takes_are_clean_but_some_are_flagged():
    flags = [r["quality_flags"] for r in rows(600)]
    flagged = [f for f in flags if f != ["none"]]
    assert 0 < len(flagged) < len(flags) / 2


def test_generated_rows_pass_the_real_ingest_validator():
    # The strongest guarantee available: synthetic data must satisfy exactly
    # the contract real model output is held to.
    shots = [{k: v for k, v in r.items() if k != "source_file"} for r in rows(300)]
    validated = rows_from_response(json.dumps(shots), VOCAB, "gs://synthetic")
    assert len(validated) == 300


def test_demo_vocabulary_uses_the_parsed_screenplay(tmp_path, monkeypatch):
    import json
    import synth
    from vocab import ProjectVocabulary

    cache = tmp_path / "vocabulary.json"
    cache.write_text(json.dumps({
        "characters": ["Ben", "Barbara"], "locations": ["Farmhouse", "Cellar"],
        "props": ["Tyre Iron"], "scenes": [],
    }))
    monkeypatch.setattr(synth, "load_vocabulary", lambda project_id="notld_1968": ProjectVocabulary(**json.loads(cache.read_text())))

    pv = synth.demo_vocabulary()
    assert isinstance(pv, ProjectVocabulary)
    # Characters come from the screenplay, not from invented names.
    assert pv.characters == ["Ben", "Barbara"]
    assert "Sarah" not in pv.characters
    # Scene ids stay synthetic: the archive spans many productions.
    assert len(pv.scenes) > 100
    assert pv.scenes[0].startswith("P01-")


def test_synthetic_rows_tagged_as_archive():
    row = next(generate_rows(VOCAB, 1, seed=0))
    assert row["project_id"] == "archive"
