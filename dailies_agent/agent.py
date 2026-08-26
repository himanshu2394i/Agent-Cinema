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

from .shot_schema import agent_instruction
from .synth import demo_vocabulary

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID", "notld_1968")
CLIP_BASE_URL = os.getenv("CLIP_BASE_URL", "http://127.0.0.1:8080")

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
    instruction=agent_instruction(
        demo_vocabulary(PROJECT_ID),
        project_id=PROJECT_ID,
        clip_base_url=CLIP_BASE_URL,
    ),
    tools=[clickhouse],
    generate_content_config=types.GenerateContentConfig(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(initial_delay=2, max_delay=30, attempts=5),
        ),
    ),
)
