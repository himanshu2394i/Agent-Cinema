"""The hand-rolled PDF writer and the Laila/Qays vocabulary it ships with.

The PDF is built byte by byte (xref offsets and all) rather than with a
library, so a silent corruption would only show up as Gemini rejecting the
upload. Reading it back with pypdf is the cheapest way to catch that here.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "scripts" / "write_laila_screenplay.py"


def _module():
    spec = importlib.util.spec_from_file_location("write_laila_screenplay", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_pdf_is_readable_and_holds_the_screenplay(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    module = _module()

    pdf = tmp_path / "screenplay.pdf"
    module.write_pdf(pdf, module.SCREENPLAY)

    text = "".join(page.extract_text() for page in pypdf.PdfReader(str(pdf)).pages)
    assert "LAILA AND QAIS" in text
    assert "DESERT CAMP" in text


def test_vocabulary_is_written_normalised_and_loadable(tmp_path, monkeypatch):
    import projects
    import vocab as vocab_module

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    projects.create_project("lailamajnu", "LailaMajnuMovie")

    module = _module()
    module.write_vocabulary(projects.vocabulary_path("lailamajnu"))

    loaded = vocab_module.load_vocabulary(projects.vocabulary_path("lailamajnu"))
    assert "Laila" in loaded.characters
    assert "Majnun" in loaded.characters
    # _titlecase must not mangle the possessive into "Laila'S Father".
    assert "Laila's Father" in loaded.characters
    assert "Kaaba" in loaded.locations
    assert "Brass Lamp" in loaded.props
    # Scene ids are slate data and stay verbatim.
    assert loaded.scenes == [str(n) for n in range(1, 9)]

    on_disk = json.loads(projects.vocabulary_path("lailamajnu").read_text())
    assert set(on_disk) == {"characters", "locations", "props", "scenes"}


def test_vocabulary_carries_no_dialogue_from_the_2018_film():
    """The legend is public domain; the 2018 feature is not."""
    module = _module()
    assert "2018" not in module.SCREENPLAY or "not the 2018" in module.SCREENPLAY
    for term in module.VOCABULARY["characters"] + module.VOCABULARY["props"]:
        assert len(term.split()) <= 4, f"{term!r} reads like a line, not a term"
