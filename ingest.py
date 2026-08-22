"""One clip in, validated shot rows out.

Gemini segments the clip and logs each shot in a single pass, constrained by
the schema built from this production's vocabulary.

The response is re-validated here even though the schema already constrains
it. That is not redundancy: these rows go straight into LowCardinality
columns, and one off-vocabulary value there is invisible at write time and
poisons every query that filters on it afterwards. Cheap check, expensive bug.
"""

import json

from shot_schema import MODEL_FIELDS, allowed_values, shot_response_schema
from vocab import ProjectVocabulary

# ponytail: flash until video captions prove it too weak; the pro tier is
# a one-word change and only ingest quality would justify the cost.
DEFAULT_MODEL = "gemini-3.6-flash"

VIDEO_MIME = "video/mp4"

# Two ways in. gs:// is production: Vertex reads Cloud Storage directly and
# the bytes never touch this process. The Files API is the local path, used
# when there is no bucket - it uploads, so keep it for small clips.
GCS_PREFIX = "gs://"
FILES_API_PREFIX = "https://generativelanguage.googleapis.com/"

PROMPT = """You are logging a clip of dailies so an editor can find it later.

Split the clip into shots - a new shot begins at every cut or camera setup
change - and log each one. Timestamps are seconds from the start of this clip.

Judge shot size by how much of the body is framed: extreme_wide is a figure
small in a landscape, wide is the full body with headroom, medium is waist up,
medium_close is chest up, close_up is the face, extreme_close_up is a detail
of the face, insert is an object with no person.

Log only what is visible. If you cannot identify a character or location from
the allowed values, use "unknown" rather than guessing the nearest one.

Put anything the vocabulary cannot express into the action field in plain
prose - it is the only place unanticipated detail survives."""


def _check(field, value, allowed: list[str], where: str) -> None:
    values = value if field.array else [value]
    for item in values:
        if item not in allowed:
            raise ValueError(
                f"{where}: field {field.name!r} got {item!r}, "
                f"which is not in its vocabulary"
            )


def rows_from_response(
    text: str, vocabulary: ProjectVocabulary, source_file: str
) -> list[dict]:
    """Parse and validate the model's shot list into ClickHouse-ready rows."""
    try:
        shots = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"shot log was not valid JSON: {text[:200]!r}") from exc

    if not isinstance(shots, list):
        raise ValueError(f"expected a list of shots, got {type(shots).__name__}")
    if not shots:
        raise ValueError(f"{source_file}: model returned no shots for this clip")

    rows = []
    for index, shot in enumerate(shots):
        where = f"{source_file} shot {index}"
        if not isinstance(shot, dict):
            raise ValueError(f"{where}: expected an object")

        row = {"source_file": source_file}
        for field in MODEL_FIELDS:
            if field.name not in shot:
                raise ValueError(f"{where}: missing field {field.name!r}")
            value = shot[field.name]

            if field.array and not isinstance(value, list):
                raise ValueError(f"{where}: field {field.name!r} should be a list")

            allowed = allowed_values(field, vocabulary)
            if allowed is not None:
                _check(field, value, allowed, where)

            row[field.name] = value

        if not row["end_seconds"] > row["start_seconds"]:
            raise ValueError(
                f"{where}: timestamps do not advance "
                f"({row['start_seconds']} -> {row['end_seconds']})"
            )
        rows.append(row)

    return rows


def log_clip(
    video_uri: str,
    vocabulary: ProjectVocabulary,
    client,
    model: str = DEFAULT_MODEL,
    source_file: str | None = None,
) -> list[dict]:
    """Log one clip of dailies from a gs:// object or a Files API URI.

    `source_file` is the clip's lasting identity in the archive. It defaults
    to the URI, which is right for gs:// but wrong for the Files API, where a
    fresh id is minted on every upload - pass the camera roll filename there
    so re-ingesting the same clip replaces its shots instead of doubling them.
    """
    if not video_uri.startswith((GCS_PREFIX, FILES_API_PREFIX)):
        raise ValueError(
            f"video_uri must be a gs:// object or a Files API URI, got {video_uri!r}"
        )

    response = client.models.generate_content(
        model=model,
        contents=[
            {"file_data": {"file_uri": video_uri, "mime_type": VIDEO_MIME}},
            {"text": PROMPT},
        ],
        config={
            "response_mime_type": "application/json",
            "response_schema": shot_response_schema(vocabulary),
        },
    )
    return rows_from_response(response.text, vocabulary, source_file or video_uri)
