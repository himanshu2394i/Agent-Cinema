from vocab import ProjectVocabulary, CRAFT_VOCAB


def test_craft_vocab_is_fixed_and_nonempty():
    # Layer 1 never varies by project.
    assert CRAFT_VOCAB["shot_size"][0] == "extreme_wide"
    assert "golden_hour" in CRAFT_VOCAB["time_of_day"]
    assert "indeterminate" in CRAFT_VOCAB["time_of_day"]


def test_strips_screenplay_parentheticals():
    # SARAH, SARAH (V.O.) and SARAH (CONT'D) are one character.
    pv = ProjectVocabulary.from_raw(
        characters=["SARAH", "SARAH (V.O.)", "SARAH (CONT'D)", "MARCUS (O.S.)"],
        locations=[], props=[], scenes=[],
    )
    assert pv.characters == ["Sarah", "Marcus"]


def test_dedupes_case_insensitively_and_preserves_order():
    pv = ProjectVocabulary.from_raw(
        characters=["Det. Ruiz", "DET. RUIZ", "Sarah"],
        locations=["Diner", "diner ", "Precinct"],
        props=[], scenes=[],
    )
    assert pv.characters == ["Det. Ruiz", "Sarah"]
    assert pv.locations == ["Diner", "Precinct"]


def test_drops_empty_and_whitespace_entries():
    pv = ProjectVocabulary.from_raw(
        characters=["", "   ", "Sarah"], locations=[], props=["  the letter "], scenes=[],
    )
    assert pv.characters == ["Sarah"]
    assert pv.props == ["The Letter"]


def test_scene_numbers_kept_verbatim():
    # Scene ids are slate data, not prose. 14B must not become "14b".
    pv = ProjectVocabulary.from_raw(
        characters=[], locations=[], props=[], scenes=["1", "14B", "3A"],
    )
    assert pv.scenes == ["1", "14B", "3A"]


def test_unknown_escape_hatch_always_present():
    # Ingest must be able to say "someone I can't identify" without breaking the enum.
    pv = ProjectVocabulary.from_raw(characters=["Sarah"], locations=[], props=[], scenes=[])
    assert "unknown" in pv.character_enum()
    assert "Sarah" in pv.character_enum()


def test_possessive_locations_are_not_mangled():
    # Screenplay headings are full of these: INT. SARAH'S CAR - NIGHT.
    # str.title() would give "Sarah'S Car".
    pv = ProjectVocabulary.from_raw(
        characters=[], locations=["SARAH'S CAR", "MARCUS' APARTMENT"], props=[], scenes=[],
    )
    assert pv.locations == ["Sarah's Car", "Marcus' Apartment"]
