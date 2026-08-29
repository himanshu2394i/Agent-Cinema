"""The query agent: natural language in, footage out.

Run with `adk web` from the project root.

The agent gets raw SQL through the official ClickHouse MCP server rather than
a set of canned query templates. Templates would be a query language nobody
asked for, and the model already writes better SQL than the DSL I would
design. Write access stays off (mcp-clickhouse defaults to read-only), so the
worst a wrong query can do is return the wrong rows.
"""

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types
from mcp import StdioServerParameters

from .editorial_tools import (
    add_to_select_list,
    get_select_list,
    inspect_clips,
    investigate_scene,
    rank_clips,
    reassess_last_ranking,
    review_evidence,
    summarize_takes,
)
from .shot_schema import agent_instruction
from .synth import demo_vocabulary
from .vocab import bundled_projects_root, load_vocabulary, vocabulary_path_for

load_dotenv()

# One process serves several productions, so PROJECT_ID is only the project a
# fresh session starts on. The session's own `project_id` state wins over it,
# and `set_active_project` is what writes that.
DEFAULT_PROJECT_ID = os.getenv("PROJECT_ID", "notld_1968")
CLIP_BASE_URL = os.getenv("CLIP_BASE_URL", "http://127.0.0.1:8080")


def active_project(state) -> str:
    """The production this session is asking about."""
    return state.get("project_id") or DEFAULT_PROJECT_ID


def _project_ids_from_vocabulary_files(root: Path) -> list[str]:
    return [p.parent.name for p in root.glob("*/vocabulary.json")]


def available_projects() -> list[str]:
    """Projects whose screenplay has been parsed - the ones we can switch to."""
    ids: list[str] = []
    seen: set[str] = set()

    def add(project_id: str) -> None:
        if project_id not in seen:
            seen.add(project_id)
            ids.append(project_id)

    try:
        from projects import list_projects

        for project in list_projects():
            add(project["id"])
    except ImportError:
        # Cloud Run ships dailies_agent/ only; there is no projects module.
        for project_id in _project_ids_from_vocabulary_files(Path("assets/projects")):
            add(project_id)
        for project_id in _project_ids_from_vocabulary_files(bundled_projects_root()):
            add(project_id)
    add(DEFAULT_PROJECT_ID)
    return sorted(i for i in ids if vocabulary_path_for(i).exists())


def _vocabulary_for(project_id: str):
    """This production's words, with synthetic scene ids only as a fallback.

    A numbered screenplay already names its scenes, and those are what the
    slate carries. An unnumbered draft (the NOTLD one) has none, so the
    synthetic archive's P##-## ids stand in - otherwise the agent is told a
    scene column exists with no idea what may be in it.
    """
    vocabulary = load_vocabulary(project_id=project_id)
    if vocabulary.scenes:
        return vocabulary
    return demo_vocabulary(project_id)


def instruction_provider(ctx) -> str:
    """System prompt for whichever production this session is on.

    Rebuilt per LLM step rather than at import, so `set_active_project` takes
    effect on the same turn it is called and one process can serve every
    movie. Being a callable also means ADK skips {}-templating the prompt.
    """
    project_id = active_project(ctx.state)
    try:
        vocabulary = _vocabulary_for(project_id)
    except FileNotFoundError:
        others = ", ".join(available_projects()) or "none"
        return (
            f"You are the assistant editor for a footage archive. The active"
            f" project is {project_id!r}, but its screenplay has not been"
            f" parsed yet, so there is no vocabulary to query against.\n\n"
            f"Tell the editor to upload a screenplay for {project_id!r} at"
            f" {CLIP_BASE_URL}/onboard, or to name another production."
            f" Projects ready now: {others}. Use set_active_project to switch"
            f" to one. Do not query the database until then."
        )
    return agent_instruction(
        vocabulary,
        project_id=project_id,
        clip_base_url=CLIP_BASE_URL,
    ) + (
        f"\n\nActive production: {project_id}. If the editor asks about a"
        f" different one, call set_active_project first - do not guess a"
        f" project_id. Ready now: {', '.join(available_projects()) or 'none'}."
        f"\n\nEditorial workflow: for clip-finding or best-take questions,"
        f" call rank_clips (or summarize_takes for one file) instead of"
        f" returning hundreds of raw SQL rows. Explain results using the"
        f" returned evidence, confidence, and alternatives. If the editor"
        f" asks why, quote the evidence fields. If they ask whether you are"
        f" sure, call reassess_last_ranking and relay challenge_answer — never"
        f" increase confidence because they challenged you. Offer"
        f" add_to_select_list when they want to keep picks — pass the ranked"
        f" clip objects, not raw SQL. When showing the select list, call"
        f" get_select_list and relay every line in `display` (clip, take,"
        f" score, confidence, selection_reason)."
        f" For story/context questions (what happens between two people,"
        f" what comes after a moment, every interaction), call"
        f" investigate_scene. It groups consecutive clips into sequences;"
        f" quote scene_id, evidence_tier, emotional_arc, and confidence."
        f" `after` is chronological clip order. Do not invent numbered"
        f" screenplay scenes when footage scene is unknown."
        f"\n\nInvestigate before you answer. Every tool call is recorded"
        f" in an evidence ledger. For any story, timeline, or 'what happens"
        f" after' question, call review_evidence before answering. If it"
        f" returns sufficient=false and remaining_budget above zero, call"
        f" the tool it names in recommended_action on missing_clips, then"
        f" review again. If the budget is spent, answer with what the"
        f" evidence establishes and say plainly which clips you could not"
        f" check - never fill the gap by guessing."
        f"\n\ninvestigate_scene only sees clips matching your filter, so"
        f" its `after` can skip footage. When the question is what happens"
        f" after a moment, answer from `immediately_after` (the literal next"
        f" clips) and say plainly that `after` is only the next matching"
        f" sequence. inspect_clips shows any other run of clips on demand."
    )


def set_active_project(project_id: str, tool_context) -> dict:
    """Point this session at a different production before querying it.

    Args:
        project_id: The project slug to switch to, e.g. 'lailamajnu'.

    Returns:
        The newly active project, or an error naming the projects that exist.
    """
    wanted = (project_id or "").strip().lower()
    ready = available_projects()
    if wanted not in ready:
        return {
            "error": f"no parsed screenplay for project {wanted!r}",
            "available": ready,
        }
    tool_context.state["project_id"] = wanted
    return {"project_id": wanted, "available": ready}

SCRIPTS = str(Path(sys.executable).parent)
SERVER = (
    shutil.which("mcp-clickhouse", path=SCRIPTS)
    or shutil.which("mcp-clickhouse")
    or "mcp-clickhouse"
)

# The MCP server is a separate process and does not inherit our .env, so the
# connection details are handed over explicitly. Nothing else is passed.
_CLICKHOUSE_KEYS = (
    "CLICKHOUSE_HOST", "CLICKHOUSE_PORT", "CLICKHOUSE_USER",
    "CLICKHOUSE_PASSWORD", "CLICKHOUSE_DATABASE",
    "CLICKHOUSE_MCP_QUERY_TIMEOUT",
)
CLICKHOUSE_ENV = {key: os.environ[key] for key in _CLICKHOUSE_KEYS if key in os.environ}
CLICKHOUSE_ENV.setdefault("CLICKHOUSE_SECURE", "true")
# mcp-clickhouse defaults to read-only; set explicitly so a misconfigured
# deploy cannot accidentally enable writes.
CLICKHOUSE_ENV.setdefault("CLICKHOUSE_ALLOW_WRITE_ACCESS", "false")
CLICKHOUSE_ENV.setdefault("CLICKHOUSE_MCP_QUERY_TIMEOUT", "30")

clickhouse = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(command=SERVER, env=CLICKHOUSE_ENV),
        # ponytail: 30s covers a cold Cloud service waking up. Raise if the
        # first query of a session still times out.
        timeout=30.0,
    ),
)

root_agent = LlmAgent(
    name="dailies",
    model=os.getenv("AGENT_MODEL", "gemini-2.5-flash"),
    description="Finds shots in a footage archive from a plain-English description.",
    instruction=instruction_provider,
    tools=[
        clickhouse,
        set_active_project,
        rank_clips,
        summarize_takes,
        investigate_scene,
        inspect_clips,
        review_evidence,
        reassess_last_ranking,
        add_to_select_list,
        get_select_list,
    ],
    generate_content_config=types.GenerateContentConfig(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(initial_delay=2, max_delay=30, attempts=5),
        ),
    ),
)
