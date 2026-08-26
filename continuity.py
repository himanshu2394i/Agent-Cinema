"""Continuity checking: does the state of a setup hold across its shots?

    python continuity.py            # every group in the real footage

A script supervisor's job is noticing that the rifle was in Ben's right hand
in one take and his left in the next. That is a question about the STATE of
what is on screen, not about what is present - which is why it needed a new
field rather than a clever query over the ones we had. Every proxy built
from presence alone produced false positives: "Old House" is logged both
interior and exterior, and both are correct, because you can shoot a house
from outside it.

So state is captured once, at ingest, in the `continuity` column, and this
module compares those descriptions as text. That split matters for cost: the
expensive pass over video already happened, and comparison is cheap
reasoning over a few hundred words.

The comparison is deliberately conservative. It is fed only shots that share
a scene and a location, only shots that actually have a description, and its
findings are checked to name shots that were really in the group - a report
pointing an editor at a clip that was never compared is worse than no report.
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass

from vocab import UNKNOWN

# ponytail: flat model choice; ingest's is separate because this call is text
# only and much cheaper.
DEFAULT_MODEL = "gemini-3.6-flash"

@dataclass(frozen=True)
class Group:
    """One character's state through one location - what a supervisor tracks."""

    character: str
    scene: str
    location: str
    shots: tuple


COMPARE_PROMPT = """You are a script supervisor checking continuity for one
person: {character}. Below are shots of {character} in the same location,
each with a description of the state of what was on screen.

Report only contradictions in {character}'s own state. Ignore anything about
anyone else in the frame.

Report only genuine contradictions: the same thing described in two
incompatible states. A rifle in the right hand in one shot and the left in
another is a contradiction. A detail mentioned in one shot and simply absent
from another is NOT - it may be out of frame, and guessing costs the editor
a wasted trip to the footage.

Ignore differences that a cut can legitimately explain: a character who has
moved, a door someone was shown opening, a prop someone was shown picking
up. You are looking for state that changed with nothing on screen to explain
it.

A description that is simply vaguer than another is not a contradiction. "A
man in light trousers" and "the group wear dark clothing" describe different
amounts, not different states.

Reference shots only by the exact labels given. Return an empty list if the
setup is consistent - that is the expected answer most of the time.

Shots:
{shots}"""

FINDING_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "detail": {"type": "string"},
            "shots": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["subject", "detail", "shots"],
    },
}


def shot_label(row: dict) -> str:
    """A stable, human-checkable handle an editor can act on."""
    return f"{row['source_file']} @{row['start_seconds']}s"


def group_for_comparison(rows: list[dict], min_shots: int = 2) -> list[Group]:
    """One group per identified character per location.

    Three exclusions, each paid for by a false positive:

    - Shots with no continuity text. An empty string is absence, not
      agreement, and offering it invites an invented contradiction.
    - Shots where nobody is identified. The first real run flagged "a man in
      light trousers" against "individuals in dark clothing" - both logged
      with characters ['unknown'], so there was never any basis for saying
      they were the same person.
    - A character seen once in a location. Continuity is a comparison.

    Grouping per character rather than per frame is what a supervisor
    actually tracks, and it keeps one person's costume out of another's.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if not str(row.get("continuity", "")).strip():
            continue
        for character in row.get("characters", []):
            if character == UNKNOWN:
                continue
            groups[(character, row.get("scene"), row.get("location"))].append(row)
    return [
        Group(character=key[0], scene=key[1], location=key[2], shots=tuple(shots))
        for key, shots in groups.items()
        if len(shots) >= min_shots
    ]


def check_group(group: Group, client, model: str = DEFAULT_MODEL) -> list[dict]:
    """Compare one character's state across a location. Text only, no video."""
    labels = {shot_label(s) for s in group.shots}
    listing = "\n".join(
        f"- {shot_label(s)}: {s['continuity']}" for s in group.shots
    )

    response = client.models.generate_content(
        model=model,
        contents=[{"text": COMPARE_PROMPT.format(
            character=group.character, shots=listing)}],
        config={
            "response_mime_type": "application/json",
            "response_schema": FINDING_SCHEMA,
        },
    )

    try:
        findings = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply was not valid JSON: {response.text[:200]!r}") from exc
    if not isinstance(findings, list):
        raise ValueError(f"expected a list of findings, got {type(findings).__name__}")

    for finding in findings:
        for named in finding.get("shots", []):
            if named not in labels:
                raise ValueError(
                    f"finding names {named!r}, which is not in this group"
                )
    return findings


def main() -> int:
    from dotenv import load_dotenv
    from google import genai

    from db import connect

    load_dotenv()
    client = genai.Client()

    pattern = sys.argv[1] if len(sys.argv) > 1 else "A001_%"
    rows = [
        dict(zip(("source_file", "start_seconds", "scene", "location",
                  "continuity", "characters", "take"), r))
        for r in connect().query(
            "SELECT source_file, start_seconds, scene, location, continuity,"
            " characters, take FROM shots WHERE source_file LIKE %(p)s"
            " AND continuity != '' ORDER BY source_file, start_seconds",
            parameters={"p": pattern},
        ).result_rows
    ]

    groups = group_for_comparison(rows)
    if not groups:
        print(f"no comparable groups in {pattern} - has anything been logged"
              " since the continuity field was added?", file=sys.stderr)
        return 1

    print(f"{len(groups)} groups to check, from {len(rows)} shots with state",
          file=sys.stderr)
    total = 0
    for group in groups:
        where = f"{group.character} in {group.location}"
        try:
            findings = check_group(group, client)
        except Exception as error:
            print(f"  {where}: FAILED {type(error).__name__}: {error}",
                  file=sys.stderr)
            continue
        if not findings:
            print(f"  {where}: consistent across {len(group.shots)} shots")
            continue
        total += len(findings)
        print(f"  {where}: {len(findings)} to check")
        for f in findings:
            print(f"    {f['subject']}: {f['detail']}")
            for s in f["shots"]:
                print(f"      {s}")

    print(f"\n{total} continuity notes across {len(groups)} groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
