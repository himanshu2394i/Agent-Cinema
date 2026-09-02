"""Screenplay -> ProjectVocabulary.

Step 1 of the pipeline. The script is what makes the rest of the system
project-agnostic: it supplies the words this production is allowed to use,
so nothing downstream has to hardcode a cast list.

Note this step is deliberately *unconstrained* - it is discovering the
vocabulary, so the model must be free to name things it finds. The enum
constraints come later, at ingest, built from whatever this returns.

The genai client is injected and every payload is a plain dict, so this
module imports nothing from the SDK and stays testable without a key.
"""

import json

from vocab import ProjectVocabulary

# ponytail: flash until video captions prove it too weak; the pro tier is
# a one-word change and only ingest quality would justify the cost.
DEFAULT_MODEL = "gemini-3.6-flash"

_STRING_LIST = {"type": "array", "items": {"type": "string"}}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "characters": _STRING_LIST,
        "locations": _STRING_LIST,
        "props": _STRING_LIST,
        "scenes": _STRING_LIST,
    },
    "required": ["characters", "locations", "props", "scenes"],
}

PROMPT = """You are reading a screenplay to build a controlled vocabulary for
logging the footage shot from it.

Extract exactly four lists:

characters - every named character who physically appears on screen. Use the
  name as written in the cue, ignoring (V.O.), (O.S.) and (CONT'D)
  decorations. Exclude labels that denote a disembodied source rather than a
  person on camera - VOICE, ANNOUNCER, COMMENTATOR, NEWSCASTER, RADIO,
  TELEVISION - unless the script shows them in frame.
locations - the distinct places from the scene headings, without the
  INT./EXT. prefix and without the trailing time of day.
props - physical objects the action lines treat as significant: objects that
  recur, are handled deliberately, or carry story weight. Not set dressing.
scenes - the scene numbers exactly as printed, in order. If the script is
  unnumbered, return an empty list.

Prefer completeness over judgement. A term wrongly included is cheap; a
character missing from this list cannot be logged in any shot."""

_FIELDS = ("characters", "locations", "props", "scenes")


def vocabulary_from_json(text: str) -> ProjectVocabulary:
    """Parse the model's JSON reply into a normalised vocabulary."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"screenplay reply was not valid JSON: {text[:200]!r}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"expected a JSON object, got {type(raw).__name__}")

    values = {}
    for name in _FIELDS:
        got = raw.get(name, [])
        if not isinstance(got, list):
            raise ValueError(f"field {name!r} should be a list, got {type(got).__name__}")
        values[name] = [str(v) for v in got]

    vocabulary = ProjectVocabulary.from_raw(**values)

    # Every screenplay has a cast. An empty one means extraction failed, and a
    # silent empty vocabulary would let ingest run and log nothing but nulls.
    if not vocabulary.characters:
        raise ValueError("screenplay parsed to no characters - extraction failed")

    return vocabulary


def parse_screenplay(pdf_bytes: bytes, client, model: str = DEFAULT_MODEL) -> ProjectVocabulary:
    """Read a screenplay PDF and return this production's vocabulary.

    `client` is a google.genai Client. Payloads are dicts rather than
    genai.types objects; confirm the SDK coerces them on first live run.
    """
    response = client.models.generate_content(
        model=model,
        contents=[
            {"inline_data": {"mime_type": "application/pdf", "data": pdf_bytes}},
            {"text": PROMPT},
        ],
        config={
            "response_mime_type": "application/json",
            "response_schema": RESPONSE_SCHEMA,
        },
    )
    return vocabulary_from_json(response.text)
