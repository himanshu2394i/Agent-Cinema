import json
import threading
from io import BytesIO
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import projects
    import projects_api

    monkeypatch.setenv("DRIVE_SYNC_INTERVAL_SECONDS", "0")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(projects_api, "PROJECTS_ROOT", tmp_path)
    return TestClient(projects_api.app)


def test_create_and_list_projects(client):
    response = client.post("/projects", json={"id": "my-film", "name": "My Film"})
    assert response.status_code == 201
    listed = client.get("/projects").json()
    assert listed[0]["id"] == "my-film"


def test_list_projects_reports_clip_count(client, tmp_path):
    import projects

    client.post("/projects", json={"id": "hasclips", "name": "Has Clips"})
    clips = projects.clips_dir("hasclips")
    (clips / "A001_C0001.mp4").write_bytes(b"data")
    (clips / "A001_C0002.mp4").write_bytes(b"data")
    (clips / "notes.txt").write_bytes(b"ignored")

    client.post("/projects", json={"id": "empty", "name": "Empty"})

    # A manifest with no clips directory at all (e.g. a legacy/imported
    # project) must report 0 rather than a glob error on a missing dir.
    no_clips_dir = tmp_path / "nodir"
    no_clips_dir.mkdir()
    (no_clips_dir / "manifest.json").write_text(
        json.dumps({"id": "nodir", "name": "No Dir"})
    )

    listed = {p["id"]: p for p in client.get("/projects").json()}
    assert listed["hasclips"]["clip_count"] == 2
    assert listed["empty"]["clip_count"] == 0
    assert listed["nodir"]["clip_count"] == 0


def test_config_reports_agents_default_project(client, monkeypatch):
    """The app page's picker needs the same default the agent falls back to.

    dailies_agent.agent.DEFAULT_PROJECT_ID reads PROJECT_ID at import time,
    so tests monkeypatch the already-imported attribute rather than the env
    var (same pattern as test_agent_session.py).
    """
    from dailies_agent import agent as agent_module

    monkeypatch.setattr(agent_module, "DEFAULT_PROJECT_ID", "lailamajnu")
    response = client.get("/config")
    assert response.status_code == 200
    assert response.json() == {"default_project_id": "lailamajnu"}


def test_create_project_provisions_drive_subfolder(client, tmp_path, monkeypatch):
    import drive_sync
    import projects

    monkeypatch.setenv("DRIVE_DAILIES_FOLDER_ID", "parentidxxxx")
    monkeypatch.setattr(drive_sync, "DAILIES_ROOT", tmp_path / "dailies")
    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)

    class FakeWriteDrive:
        def find_child_folder(self, parent_id, name):
            assert parent_id == "parentidxxxx"
            assert name == "Project2"
            return None

        def create_folder(self, parent_id, name):
            return "childfolder1"

        def list_mp4s(self, folder_id):
            return []

        def upload(self, path, folder_id):
            return None

    monkeypatch.setattr(drive_sync, "try_drive_client", lambda: FakeWriteDrive())
    response = client.post("/projects", json={"id": "project2", "name": "Project2"})
    assert response.status_code == 201
    assert response.json()["drive_folder_id"] == "childfolder1"
    assert (tmp_path / "dailies" / "Project2").is_dir()


def test_upload_screenplay_parses_vocabulary(client, monkeypatch):
    from vocab import ProjectVocabulary

    fake_vocab = ProjectVocabulary.from_raw(
        characters=["Ben"], locations=["Farmhouse"], props=["Rifle"], scenes=[]
    )

    def fake_parse(pdf_bytes, client):
        return fake_vocab

    monkeypatch.setattr("projects_api.parse_screenplay", fake_parse)

    client.post("/projects", json={"id": "notld", "name": "NOTLD"})
    response = client.post(
        "/projects/notld/screenplay",
        files={"file": ("script.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["characters"] == ["Ben"]

    vocab = client.get("/projects/notld/vocabulary").json()
    assert vocab["locations"] == ["Farmhouse"]


def test_serve_and_watch_project_clip(client, tmp_path, monkeypatch):
    import projects
    import projects_api

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(projects_api, "PROJECTS_ROOT", tmp_path)

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    clip_path = projects.clips_dir("demo") / "A001_C0007.mp4"
    clip_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    media = client.get("/projects/demo/media/A001_C0007.mp4")
    assert media.status_code == 200
    assert media.content.startswith(b"\x00\x00")
    assert "video" in media.headers["content-type"]

    watch = client.get("/watch?project=demo&file=A001_C0007.mp4")
    assert watch.status_code == 200
    assert b"<video" in watch.content
    assert b"/projects/demo/media/A001_C0007.mp4" in watch.content


def test_missing_clip_returns_404(client):
    client.post("/projects", json={"id": "empty", "name": "Empty"})
    assert client.get("/projects/empty/media/missing.mp4").status_code == 404


def test_upload_clip_pushes_to_drive_when_folder_linked(client, tmp_path, monkeypatch):
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    client.post("/projects", json={"id": "demo", "name": "Demo"})
    client.post(
        "/projects/demo/drive",
        json={"folder": "https://drive.google.com/drive/folders/1AbCDefGhIjk_lmnoPQRS"},
    )
    uploaded = []

    class FakeDrive:
        def upload(self, path, folder_id):
            uploaded.append((path.name, folder_id))

        def list_mp4s(self, folder_id):
            return []

        def download(self, file_id, dest):
            dest.write_bytes(b"x")

    monkeypatch.setattr("projects_api.try_drive_client", lambda: FakeDrive())
    res = client.post(
        "/projects/demo/clips",
        files={"file": ("A001_C0009.mp4", b"data", "video/mp4")},
    )
    assert res.status_code == 200
    assert res.json()["saved"] == "A001_C0009.mp4"
    assert res.json()["uploaded_to_drive"] is True
    assert uploaded == [("A001_C0009.mp4", "1AbCDefGhIjk_lmnoPQRS")]


def test_attach_drive_folder_and_sync(client, tmp_path, monkeypatch):
    import drive_sync
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    monkeypatch.setattr(drive_sync, "list_projects", projects.list_projects)
    monkeypatch.setattr(drive_sync, "load_manifest", projects.load_manifest)
    monkeypatch.setattr(drive_sync, "project_dir", projects.project_dir)
    monkeypatch.setattr(drive_sync, "clips_dir", projects.clips_dir)

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    attach = client.post(
        "/projects/demo/drive",
        json={"folder": "https://drive.google.com/drive/folders/1AbCDefGhIjk_lmnoPQRS"},
    )
    assert attach.status_code == 200
    assert attach.json()["drive_folder_id"] == "1AbCDefGhIjk_lmnoPQRS"
    assert client.get("/projects/demo").json()["drive_folder_id"] == "1AbCDefGhIjk_lmnoPQRS"

    class FakeDrive:
        def list_mp4s(self, folder_id):
            return [{"id": "f2", "name": "A001_C0002.mp4"}]

        def download(self, file_id, dest):
            dest.write_bytes(b"clip")

    monkeypatch.setattr("projects_api.try_drive_client", lambda: FakeDrive())
    synced = client.post("/projects/demo/drive/sync")
    assert synced.status_code == 200
    assert synced.json()["downloaded"] == ["A001_C0002.mp4"]
    assert (projects.clips_dir("demo") / "A001_C0002.mp4").is_file()


def test_serve_screenplay_pdf_when_on_disk(client, tmp_path, monkeypatch):
    import projects

    monkeypatch.setattr(projects, "PROJECTS_ROOT", tmp_path)
    client.post("/projects", json={"id": "laila", "name": "Laila"})
    projects.screenplay_path("laila").write_bytes(b"%PDF-1.4 test")

    status = client.get("/projects/laila").json()
    assert status["has_screenplay"] is True

    pdf = client.get("/projects/laila/screenplay.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "pdf" in pdf.headers["content-type"]


def _fake_session(ledger, state_extra=None):
    state = {"project_id": "lailamajnu", "investigation": ledger}
    state.update(state_extra or {})
    return {"id": "s1", "state": state}


def test_trace_page_renders_the_investigation_steps(client, monkeypatch):
    import projects_api

    ledger = [
        {"step": 1, "tool": "investigate_scene", "question": "talks to father",
         "clips_seen": ["C0100", "C0109"], "finding": "anchor C0100-C0100.",
         "evidence_tier": "DIRECT_INTERACTION", "invocation": "t1"},
        {"step": 2, "tool": "inspect_clips", "question": "What is on C0101-C0103?",
         "clips_seen": ["C0101", "C0102", "C0103"], "finding": "3 clips with footage.",
         "evidence_tier": "METADATA_ONLY", "invocation": "t1"},
    ]
    monkeypatch.setattr(projects_api, "_adk_session", lambda *a, **k: _fake_session(ledger))
    page = client.get("/trace", params={"session": "s1"})
    assert page.status_code == 200
    body = page.text
    assert "Mapped the sequence" in body
    assert "Inspected the footage" in body
    assert "C0101-C0103" in body          # collapsed range
    assert "3 clips with footage." in body
    assert "Evidence sufficient" in body


def test_trace_page_names_an_open_gap_rather_than_claiming_sufficiency(client, monkeypatch):
    import projects_api

    ledger = [
        {"step": 1, "tool": "investigate_scene", "question": "after?",
         "clips_seen": ["C0100"], "finding": "anchor.", "evidence_tier": None,
         "pending_followup": [101, 103], "invocation": "t1"},
    ]
    monkeypatch.setattr(projects_api, "_adk_session", lambda *a, **k: _fake_session(ledger))
    body = client.get("/trace", params={"session": "s1"}).text
    assert "C0101" in body
    assert "Evidence sufficient" not in body


def test_trace_page_says_so_when_nothing_has_been_investigated(client, monkeypatch):
    import projects_api

    monkeypatch.setattr(projects_api, "_adk_session", lambda *a, **k: _fake_session([]))
    body = client.get("/trace", params={"session": "s1"}).text
    assert "No investigation recorded" in body


def test_trace_page_escapes_session_input(client, monkeypatch):
    import projects_api

    monkeypatch.setattr(projects_api, "_adk_session", lambda *a, **k: _fake_session([]))
    body = client.get("/trace", params={"session": "<script>x</script>"}).text
    assert "<script>x</script>" not in body


def test_trace_page_lists_sessions_when_none_is_named(client, monkeypatch):
    """A panel you can only reach by guessing an id is not reachable."""
    import projects_api

    monkeypatch.setattr(
        projects_api, "_adk_sessions",
        lambda *a, **k: [{"id": "s1", "lastUpdateTime": 2}, {"id": "s2", "lastUpdateTime": 1}],
    )
    body = client.get("/trace").text
    assert "s1" in body and "s2" in body
    assert "/trace?session=s1" in body


def test_trace_page_only_shows_budget_for_a_single_turn(client, monkeypatch):
    """Budget is per question, so a whole-session view must not quote one."""
    import projects_api

    ledger = [
        {"step": 1, "tool": "rank_clips", "question": "q1", "clips_seen": ["C0063"],
         "finding": "ranked", "evidence_tier": None, "invocation": "t1"},
        {"step": 2, "tool": "inspect_clips", "question": "q2", "clips_seen": ["C0101"],
         "finding": "looked", "evidence_tier": None, "invocation": "t2"},
    ]
    monkeypatch.setattr(projects_api, "_adk_session", lambda *a, **k: _fake_session(ledger))
    whole = client.get("/trace", params={"session": "s1"}).text
    assert "budget" not in whole.lower()
    one_turn = client.get("/trace", params={"session": "s1", "turn": "t2"}).text
    assert "budget 4 left" in one_turn


# --- POST/GET /projects/{project_id}/ingest -------------------------------
#
# _run_ingest_batch is the seam: it does the real genai/ClickHouse wiring
# (see projects_api.py), so tests fake that one function instead of three
# layers of client/db/vocabulary - the same style run_batch's own tests use
# for log_clip/replace_clip/logged_sources.


def test_starting_ingest_returns_immediately_and_reports_in_flight(client, monkeypatch):
    import projects_api

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    monkeypatch.setattr(projects_api, "_run_ingest_batch", lambda project_id: (2, 5, [], []))

    res = client.post("/projects/demo/ingest")
    assert res.status_code == 202
    assert res.json()["running"] is True


def test_ingest_status_reports_counts_after_a_run_completes(client, monkeypatch):
    import projects_api

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    monkeypatch.setattr(
        projects_api, "_run_ingest_batch",
        lambda project_id: (3, 7, ["bad.mp4"], ["old.mp4"]),
    )

    client.post("/projects/demo/ingest")
    status = client.get("/projects/demo/ingest").json()

    assert status["running"] is False
    assert status["done"] == 1  # 3 clips - 1 failed - 1 skipped
    assert status["failed"] == ["bad.mp4"]
    assert status["skipped"] == ["old.mp4"]
    assert status["error"] is None


def test_ingest_status_records_the_error_from_a_failed_run(client, monkeypatch):
    import projects_api

    client.post("/projects", json={"id": "demo", "name": "Demo"})

    def fake_run(project_id):
        raise RuntimeError("ClickHouse is down")

    monkeypatch.setattr(projects_api, "_run_ingest_batch", fake_run)

    client.post("/projects/demo/ingest")
    status = client.get("/projects/demo/ingest").json()

    assert status["running"] is False
    assert "ClickHouse is down" in status["error"]


def test_starting_ingest_twice_does_not_launch_a_second_run(client, monkeypatch):
    """The bug this guards against: two concurrent runs on the same clips
    would double-spend Gemini calls."""
    import projects_api

    client.post("/projects", json={"id": "demo", "name": "Demo"})

    calls = []
    started = threading.Event()
    release = threading.Event()

    def fake_run(project_id):
        calls.append(project_id)
        started.set()
        assert release.wait(timeout=5), "test deadlocked"
        return (1, 1, [], [])

    monkeypatch.setattr(projects_api, "_run_ingest_batch", fake_run)

    thread = threading.Thread(target=lambda: client.post("/projects/demo/ingest"))
    thread.start()
    assert started.wait(timeout=5), "first run never started"

    second = client.post("/projects/demo/ingest")
    assert second.json()["running"] is True

    release.set()
    thread.join(timeout=5)

    assert calls == ["demo"]


def test_ingest_unknown_project_404s(client):
    assert client.post("/projects/ghost/ingest").status_code == 404
    assert client.get("/projects/ghost/ingest").status_code == 404


# --- GET /projects/{project_id}/selects.csv -------------------------------


def test_selects_csv_unknown_project_404s(client):
    assert client.get("/projects/ghost/selects.csv").status_code == 404


def test_selects_csv_empty_project_is_header_only(client):
    client.post("/projects", json={"id": "empty", "name": "Empty"})
    response = client.get("/projects/empty/selects.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert 'filename="empty-selects.csv"' in response.headers["content-disposition"]
    rows = response.text.strip("\r\n").splitlines()
    assert rows == ["clip,take,score,confidence,reason,watch_url"]


def test_selects_json_returns_stored_items_with_watch_urls(client, tmp_path):
    import projects

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    selects_path = projects.project_dir("demo") / "selects.json"
    selects_path.write_text(
        json.dumps([{"clip": "A001_C0123.mp4", "best_take": 2, "ranking_score": 0.9,
                      "confidence": "high", "selection_reason": "clean take"}])
    )

    response = client.get("/projects/demo/selects.json")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    item = body["selects"][0]
    assert item["clip"] == "A001_C0123.mp4"
    assert "project=demo" in item["watch_url"]
    assert "file=A001_C0123.mp4" in item["watch_url"]


def test_selects_json_unknown_project_404s(client):
    assert client.get("/projects/ghost/selects.json").status_code == 404


def test_selects_csv_contains_stored_rows_and_survives_comma_and_quote(client, tmp_path):
    import projects

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    selects_path = projects.project_dir("demo") / "selects.json"
    selects_path.write_text(
        json.dumps(
            [
                {
                    "clip": "A001_C0123.mp4",
                    "best_take": 7,
                    "ranking_score": 0.94,
                    "confidence": "high",
                    "selection_reason": 'she says "no, wait" then cries, softly',
                }
            ]
        )
    )

    response = client.get("/projects/demo/selects.csv")
    assert response.status_code == 200

    import csv
    import io

    reader = csv.reader(io.StringIO(response.text))
    header, row = list(reader)
    assert header == ["clip", "take", "score", "confidence", "reason", "watch_url"]
    assert row[0] == "A001_C0123.mp4"
    assert row[1] == "7"
    assert row[2] == "0.94"
    assert row[3] == "high"
    assert row[4] == 'she says "no, wait" then cries, softly'
    assert "A001_C0123.mp4" in row[5]
    assert "project=demo" in row[5]


# --- POST /projects/{project_id}/session and /ask ------------------------
#
# The browser never talks to the ADK server directly - these two endpoints
# proxy it. Session creation and the happy-path answer are faked by
# monkeypatching the seam functions (same style as _adk_session above);
# the unreachable-server case is exercised for real, against a closed local
# port, so the test proves the actual urllib error path produces a clean
# 502 instead of a hang or a raw traceback.


def test_start_agent_session_scopes_state_to_the_project(client, monkeypatch):
    import projects_api

    client.post("/projects", json={"id": "demo", "name": "Demo"})
    calls = []

    def fake_post_json(path, payload, timeout=15):
        calls.append((path, payload))
        return {"id": "sess-1"}

    monkeypatch.setattr(projects_api, "_adk_post_json", fake_post_json)

    response = client.post("/projects/demo/session")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "session_id": "sess-1",
        "user_id": "editor",
        "app_name": projects_api.ADK_APP_NAME,
        "project_id": "demo",
    }
    (path, payload), = calls
    assert path == f"/apps/{projects_api.ADK_APP_NAME}/users/editor/sessions"
    assert payload == {"state": {"project_id": "demo"}}


def test_start_agent_session_unknown_project_404s(client):
    assert client.post("/projects/ghost/session").status_code == 404


def test_ask_agent_returns_the_final_prose_answer(client, monkeypatch):
    import projects_api

    client.post("/projects", json={"id": "demo", "name": "Demo"})

    # A realistic run: a tool-call event carrying no text, then the model's
    # wrap-up sentence. Only the second should surface as the answer.
    sse_body = (
        'data: {"content": {"role": "model", "parts": [{"functionCall": '
        '{"name": "rank_clips", "args": {}}}]}}\n\n'
        'data: {"content": {"role": "model", "parts": [{"text": '
        '"Best take is A001_C0049.mp4, take 2."}]}}\n\n'
    ).encode()

    calls = []

    def fake_post_raw(path, payload, timeout):
        calls.append((path, payload, timeout))
        return sse_body

    monkeypatch.setattr(projects_api, "_adk_post_raw", fake_post_raw)

    response = client.post(
        "/projects/demo/ask",
        json={"session_id": "sess-1", "question": "best take of the well scene"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "answer": "Best take is A001_C0049.mp4, take 2.",
        "session_id": "sess-1",
    }
    (path, payload, _timeout), = calls
    assert path == "/run_sse"
    assert payload["session_id"] == "sess-1"
    assert payload["new_message"]["parts"] == [{"text": "best take of the well scene"}]
    assert payload["streaming"] is False


def test_ask_agent_rejects_a_blank_question(client):
    client.post("/projects", json={"id": "demo", "name": "Demo"})
    response = client.post(
        "/projects/demo/ask", json={"session_id": "sess-1", "question": "   "}
    )
    assert response.status_code == 400


def test_ask_agent_unknown_project_404s(client):
    response = client.post(
        "/projects/ghost/ask", json={"session_id": "sess-1", "question": "hi"}
    )
    assert response.status_code == 404


def test_unreachable_agent_server_produces_a_clean_error_not_a_hang(client, monkeypatch):
    """No fake here - a real closed port, to prove the actual urllib.error/OSError
    path degrades to a readable 502 naming the host, not a 500 or a hang."""
    import projects_api

    monkeypatch.setattr(projects_api, "ADK_BASE_URL", "http://127.0.0.1:1")
    client.post("/projects", json={"id": "demo", "name": "Demo"})

    session_response = client.post("/projects/demo/session")
    assert session_response.status_code == 502
    detail = session_response.json()["detail"]
    assert "127.0.0.1:1" in detail
    assert "adk api_server" in detail

    ask_response = client.post(
        "/projects/demo/ask", json={"session_id": "sess-1", "question": "hi"}
    )
    assert ask_response.status_code == 502
    assert "127.0.0.1:1" in ask_response.json()["detail"]


def test_app_page_is_served(client):
    response = client.get("/app")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
