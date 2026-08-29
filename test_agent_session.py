"""Per-session project scoping for the query agent.

One `adk web` process serves several productions, so the project a session
talks about has to come from session state rather than from PROJECT_ID at
import time.
"""

import json
import sys

import pytest

pytest.importorskip("google.adk")


@pytest.fixture
def agent_module():
    """Import dailies_agent without leaving its dir on sys.path.

    dailies_agent/__init__.py prepends its own directory so the Cloud Run
    bundle resolves its copies of vocab.py/shot_schema.py. Left in place it
    would shadow the repo-root copies for every test that runs after this
    file, so it is undone here.
    """
    original_path = list(sys.path)
    before = set(sys.modules)
    from dailies_agent import agent

    yield agent
    sys.path[:] = original_path
    for name in set(sys.modules) - before:
        if name.split(".")[0] in {"vocab", "shot_schema", "synth"}:
            del sys.modules[name]


class FakeContext:
    """Stands in for ReadonlyContext / ToolContext: both expose .state."""

    def __init__(self, state=None):
        self.state = {} if state is None else state


def _write_vocabulary(root, project_id, **terms):
    import projects

    projects.create_project(project_id, project_id)
    projects.vocabulary_path(project_id).write_text(
        json.dumps(
            {
                "characters": terms.get("characters", []),
                "locations": terms.get("locations", []),
                "props": terms.get("props", []),
                "scenes": terms.get("scenes", []),
            }
        )
    )


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    _write_vocabulary(
        tmp_path, "lailamajnu",
        characters=["Majnun", "Laila"], locations=["Kaaba"],
        props=["Brass Lamp"], scenes=["1", "2"],
    )
    _write_vocabulary(
        tmp_path, "notld",
        characters=["Ben"], locations=["Farmhouse"], props=["Rifle"],
    )
    return tmp_path


def test_active_project_falls_back_to_env_default(agent_module, monkeypatch):
    monkeypatch.setattr(agent_module, "DEFAULT_PROJECT_ID", "notld_1968")
    assert agent_module.active_project(FakeContext().state) == "notld_1968"
    assert agent_module.active_project({"project_id": "lailamajnu"}) == "lailamajnu"


def test_instruction_scopes_to_the_session_project(agent_module, two_projects):
    laila = agent_module.instruction_provider(FakeContext({"project_id": "lailamajnu"}))
    assert "project_id = 'lailamajnu'" in laila
    assert "Majnun" in laila
    assert "Ben" not in laila

    notld = agent_module.instruction_provider(FakeContext({"project_id": "notld"}))
    assert "project_id = 'notld'" in notld
    assert "Ben" in notld
    assert "Majnun" not in notld


def _scene_line(instruction):
    """The `scene (one of): ...` enum line, not the prose that mentions scenes.

    POPULATION_NOTE quotes a synthetic id as an example, so a plain substring
    check on the whole prompt would pass no matter what the enum holds.
    """
    return next(
        line for line in instruction.splitlines() if line.strip().startswith("scene (")
    )


def test_numbered_screenplay_keeps_its_own_scenes(agent_module, two_projects):
    """Synthetic P##-## ids are only a stand-in for an unnumbered draft."""
    laila = _scene_line(
        agent_module.instruction_provider(FakeContext({"project_id": "lailamajnu"}))
    )
    assert "'1', '2'" in laila
    assert "P0" not in laila

    notld = _scene_line(
        agent_module.instruction_provider(FakeContext({"project_id": "notld"}))
    )
    assert "P01-1" in notld


def test_set_active_project_switches_the_session(agent_module, two_projects):
    ctx = FakeContext({"project_id": "notld"})
    result = agent_module.set_active_project("lailamajnu", ctx)

    assert result["project_id"] == "lailamajnu"
    assert ctx.state["project_id"] == "lailamajnu"
    assert "Majnun" in agent_module.instruction_provider(ctx)


def test_set_active_project_rejects_unknown_and_leaves_state_alone(
    agent_module, two_projects
):
    ctx = FakeContext({"project_id": "notld"})
    result = agent_module.set_active_project("no-such-film", ctx)

    assert "error" in result
    assert "lailamajnu" in result["available"]
    assert ctx.state["project_id"] == "notld"


def test_missing_vocabulary_explains_itself_instead_of_raising(
    agent_module, tmp_path, monkeypatch
):
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    projects.create_project("bare", "Bare")

    instruction = agent_module.instruction_provider(FakeContext({"project_id": "bare"}))
    assert "bare" in instruction
    assert "screenplay" in instruction.lower()


def test_bundled_vocabulary_enables_cloud_run_project_switch(
    agent_module, tmp_path, monkeypatch
):
    """Cloud Run has no projects module; vocab is staged under dailies_agent/assets."""
    import builtins
    from dailies_agent import vocab

    assets = tmp_path / "assets"
    bundled = assets / "projects" / "cloud-test"
    bundled.mkdir(parents=True)
    (bundled / "vocabulary.json").write_text(
        json.dumps(
            {
                "characters": ["Laila"],
                "locations": ["Desert"],
                "props": ["Lamp"],
                "scenes": ["1"],
            }
        )
    )
    monkeypatch.setattr(vocab, "_PACKAGE_ASSETS", assets)
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "projects":
            raise ImportError("cloud run bundle")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ready = agent_module.available_projects()
    assert "cloud-test" in ready
    result = agent_module.set_active_project("cloud-test", FakeContext())
    assert result["project_id"] == "cloud-test"
    assert "Laila" in agent_module.instruction_provider(
        FakeContext({"project_id": "cloud-test"})
    )
    assert vocab.vocabulary_path_for("cloud-test") == bundled / "vocabulary.json"
