"""One field table, two outputs: the Gemini response schema and the ClickHouse DDL.

This module exists for a single reason. The model writes values at ingest and
the agent filters on values at query time, and if those two vocabularies ever
diverge the system fails in the worst possible way - queries return zero rows
while every component reports success.

So both artefacts are generated from MODEL_FIELDS below. Adding a field means
editing one tuple; the schema and the table cannot drift apart.
"""

from dataclasses import dataclass

from .vocab import CRAFT_VOCAB, ProjectVocabulary

CRAFT = "craft"            # fixed cinematographic vocabulary
PROJECT = "project"        # derived from the screenplay
TEXT = "text"              # free prose, never filtered with equality
NUMBER = "number"
INTEGER = "integer"


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    clickhouse: str
    source: str | None = None   # key into CRAFT_VOCAB, or ProjectVocabulary attr
    array: bool = False


# ponytail: `take` is read off the slate. Productions with a strict filename
# convention should parse it instead and overwrite - slates get misread.
MODEL_FIELDS: tuple[Field, ...] = (
    Field("scene", PROJECT, "LowCardinality(String)", source="scenes"),
    Field("take", INTEGER, "UInt16"),
    Field("start_seconds", NUMBER, "Float32"),
    Field("end_seconds", NUMBER, "Float32"),
    Field("shot_size", CRAFT, "LowCardinality(String)", source="shot_size"),
    Field("camera_movement", CRAFT, "LowCardinality(String)", source="camera_movement"),
    Field("time_of_day", CRAFT, "LowCardinality(String)", source="time_of_day"),
    Field("int_ext", CRAFT, "LowCardinality(String)", source="int_ext"),
    Field("location", PROJECT, "LowCardinality(String)", source="locations"),
    Field("characters", PROJECT, "Array(LowCardinality(String))",
          source="characters", array=True),
    Field("props", PROJECT, "Array(LowCardinality(String))",
          source="props", array=True),
    Field("quality_flags", CRAFT, "Array(LowCardinality(String))",
          source="quality_flags", array=True),
    # Free text is the safety net: anything the vocabulary failed to
    # anticipate is still captured here and still searchable.
    Field("dialogue", TEXT, "String"),
    Field("action", TEXT, "String"),
    # Continuity is the state of things, not their presence: sleeves rolled,
    # lamp lit, rifle in which hand. It cannot be enumerated, so it stays
    # prose and is compared as prose rather than filtered on.
    Field("continuity", TEXT, "String"),
)

# Written by the ingest job, not by the model, so they are absent from the
# response schema by design.
DB_ONLY_COLUMNS = {"shot_id", "source_file", "project_id", "ingested_at"}

ORDER_BY = "(scene, take, start_seconds)"


def allowed_values(field: Field, vocabulary: ProjectVocabulary) -> list[str] | None:
    """The closed set for a field, or None if it is free text or a number."""
    if field.kind == CRAFT:
        return CRAFT_VOCAB[field.source]
    if field.kind == PROJECT:
        return vocabulary.enum_of(field.source)
    return None


def _leaf(field: Field, vocabulary: ProjectVocabulary) -> dict:
    """The JSON schema for one value of this field."""
    allowed = allowed_values(field, vocabulary)
    if allowed is not None:
        return {"type": "string", "enum": allowed}
    if field.kind == TEXT:
        return {"type": "string"}
    return {"type": field.kind}


def shot_response_schema(vocabulary: ProjectVocabulary) -> dict:
    """Response schema for the ingest call: a list of shots found in one clip.

    Every closed field is an enum, so an off-vocabulary value is not a
    possible output rather than merely a discouraged one.
    """
    properties = {}
    for field in MODEL_FIELDS:
        leaf = _leaf(field, vocabulary)
        properties[field.name] = (
            {"type": "array", "items": leaf} if field.array else leaf
        )

    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": [f.name for f in MODEL_FIELDS],
        },
    }


def _all_columns(table: str) -> list[tuple[str, str]]:
    return [
        ("shot_id", "UUID DEFAULT generateUUIDv4()"),
        ("source_file", "String"),
        ("project_id", "LowCardinality(String)"),
        *[(f.name, f.clickhouse) for f in MODEL_FIELDS],
        ("ingested_at", "DateTime DEFAULT now()"),
    ]


def alter_statements(table: str = "shots") -> list[str]:
    """Bring an existing table up to the current field table.

    CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
    so without these a new field lands in the response schema and the DDL
    while the live table stays one column short, and the next insert fails
    on an unknown column.
    """
    return [
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {type_}"
        for name, type_ in _all_columns(table)
    ]


def clickhouse_ddl(table: str = "shots") -> str:
    """CREATE TABLE matching the response schema, column for column."""
    columns = _all_columns(table)
    width = max(len(name) for name, _ in columns)
    body = ",\n".join(f"    {name:<{width}} {type_}" for name, type_ in columns)
    return (
        f"CREATE TABLE IF NOT EXISTS {table} (\n{body}\n)\n"
        f"ENGINE = MergeTree\n"
        f"ORDER BY {ORDER_BY}"
    )


# A whole production archive can hold thousands of scene ids. Listing them
# all costs more tokens than it saves lookups, so past this the agent is told
# to query for the values instead.
MAX_ENUMERATED = 40

AGENT_ROLE = """You are the assistant editor for a footage archive. You answer
questions about what was shot by querying the ClickHouse table below, then
reporting the clips in plain language.

Always cite source_file and take so the editor can pull the clip."""

POPULATION_NOTE = """This table holds two different populations of rows -
know which one a question is about before you filter:

- Real logged footage: source_file looks like 'A001_C0001.mp4' (a camera
  roll name). Its screenplay is unnumbered, so every real row has
  scene = 'unknown'. When the user says "the footage", "the clips", or
  names a clip file, they mean these rows.
- Synthetic filler: source_file looks like 'gs://dailies/A004_C0834.mp4'.
  These rows exist only to test query performance at scale and carry the
  P##-## scene ids listed below. A scene-id filter (e.g. scene = 'P07-14B')
  can only ever match synthetic rows, never the real footage.

Do not treat a valid-looking scene id as evidence a query is about real
footage, and do not expect real footage to have a numbered scene."""

ZERO_ROW_PROTOCOL = """If a query returns no rows, do not report "no footage"
yet. An empty result is far more often a wrong filter than an empty archive.
Before answering, in this order:

1. Check every literal you used against the allowed values listed above.
   They are exact - 'golden_hour' not 'Golden Hour', 'Det. Ruiz' not 'Ruiz'.
2. Drop the least important filter and run it again, to find which condition
   emptied the result.
3. If the term is not in any vocabulary above, it was never a column - search
   the prose instead with `action ILIKE '%term%' OR dialogue ILIKE '%term%'`.

Only after those say the archive genuinely has nothing. Then say which filter
excluded everything, so the editor knows what to relax."""

QUERY_GUARDRAILS = """Query safety (required on every SQL call):

- SELECT only. Never INSERT, UPDATE, DELETE, DROP, TRUNCATE, or ALTER.
- Cap rows with LIMIT (default LIMIT 1000). Do not use SETTINGS
  max_result_rows or max_execution_time — the database user is read-only
  and cannot change those settings.
- Prefer filtered queries over SELECT * without a WHERE clause.
- If a question needs more than 1000 rows, raise LIMIT deliberately and
  say so in your answer."""


def agent_instruction(
    vocabulary: ProjectVocabulary,
    table: str = "shots",
    project_id: str = "notld_1968",
) -> str:
    """System prompt for the query agent.

    Generated from MODEL_FIELDS, so the values the agent filters on are the
    same values ingest was constrained to write. This is the read half of the
    guarantee; shot_response_schema is the write half.
    """
    lines = []
    for field in MODEL_FIELDS:
        allowed = allowed_values(field, vocabulary)
        if allowed is not None:
            kind = "array, use has()" if field.array else "one of"
            head = allowed[:MAX_ENUMERATED]
            shown = ", ".join(repr(v) for v in head)
            if len(allowed) > MAX_ENUMERATED:
                shown += (
                    f" ... and {len(allowed) - MAX_ENUMERATED} more; run"
                    f" SELECT DISTINCT {field.name} FROM {table} for the rest"
                )
            lines.append(f"  {field.name} ({kind}): {shown}")
        else:
            lines.append(f"  {field.name}: {field.clickhouse}, free text")
    lines.append(
        "  source_file: String, the clip this shot came from. Its shape tells"
        " you which population the row belongs to - see below."
    )
    lines.append(
        f"  project_id: always filter with project_id = '{project_id}' unless"
        " the user explicitly asks about the synthetic archive (project_id ="
        " 'archive')."
    )

    return "\n\n".join([
        AGENT_ROLE,
        f"Table `{table}`. Columns and their allowed values:",
        "\n".join(lines),
        POPULATION_NOTE,
        QUERY_GUARDRAILS,
        ZERO_ROW_PROTOCOL,
    ])
