"""Pass one: propose a vocabulary for footage that has no screenplay.

Documentary, interview and event coverage arrive without a script, so there
is nothing to derive a controlled vocabulary from. This module builds one by
looking at the footage itself.

    python survey.py assets/clips 8 > proposal.json

It is deliberately two passes, not one. Pass one asks Gemini what it sees in
a sample of clips with no constraints at all - constraining discovery to a
vocabulary would be circular, since the vocabulary is what we are looking
for. The recurring terms become a proposal, a human edits it, and only then
does the constrained logging in ingest.py run against the whole directory.

The judgement that matters is the threshold. A face in one clip is a
passer-by; a face in six is a subject worth a column. Counting is per clip
rather than per mention, so one talkative clip cannot promote a term on its
own, and terms are normalised before they are counted - otherwise "woman in
red coat" and "Woman In Red Coat" are tallied separately and a subject who
appears in every clip falls below the threshold twice over.
"""

import json
import sys
from collections import Counter
from pathlib import Path

from vocab import ProjectVocabulary, normalize_terms

# ponytail: flat threshold. If clip counts vary wildly, make it a fraction of
# clips surveyed instead.
MIN_CLIPS = 2

FIELDS = ("characters", "locations", "props")

_STRING_LIST = {"type": "array", "items": {"type": "string"}}

SURVEY_SCHEMA = {
    "type": "object",
    "properties": {field: _STRING_LIST for field in FIELDS},
    "required": list(FIELDS),
}

SURVEY_PROMPT = """You are watching a clip of unscripted footage to work out
who and what recurs in it. There is no screenplay, so nothing is named for
you yet.

characters - every person who appears. There are no names available, so
  describe each one by what would still identify them in another clip:
  "woman in red coat", "man with clipboard", "bearded interviewer". Use
  appearance and role, not what they happen to be doing in this shot - a
  person who is sitting here may be standing in the next clip.
locations - the distinct places the footage is shot in, described the same
  durable way: "hotel lobby", "loading dock", "kitchen".
props - objects that are handled deliberately or carry meaning. Not set
  dressing.

Use the same wording for the same person or place every time, because these
descriptions are about to become a controlled vocabulary and two spellings
of one subject will split them into two."""

CARRY_FORWARD = """
You have already described the following in earlier clips of this same
shoot. If you see any of them again, reuse the exact wording below rather
than inventing a new description - the same person called two things is
counted as two people, and then neither is recognised as recurring.

{known}

Add new descriptions only for people, places and objects genuinely not in
that list."""


def sample_evenly(videos: list, count: int) -> list:
    """Pick `count` items spread across the list, in order.

    Surveying every clip would cost as much as logging them, which defeats
    the point of looking before committing.
    """
    if count >= len(videos):
        return list(videos)
    stride = len(videos) / count
    return [videos[int(i * stride)] for i in range(count)]


def observe_clip(
    video_uri: str, client, model: str = "gemini-3.6-flash",
    known: dict[str, list[str]] | None = None,
) -> dict:
    """Ask what is in one clip, with no vocabulary imposed.

    `known` is what earlier clips in the same survey produced. Each clip is
    an independent call with no memory of the last, so without this the model
    describes one person three different ways across three clips and the
    recurrence count - the entire basis of the proposal - reads zero.
    """
    prompt = SURVEY_PROMPT
    listed = chr(10).join(
        f"{field}: " + ", ".join(known[field])
        for field in FIELDS if known and known.get(field)
    )
    if listed:
        prompt += CARRY_FORWARD.format(known=listed)

    response = client.models.generate_content(
        model=model,
        contents=[
            {"file_data": {"file_uri": video_uri, "mime_type": "video/mp4"}},
            {"text": prompt},
        ],
        config={
            "response_mime_type": "application/json",
            "response_schema": SURVEY_SCHEMA,
        },
    )
    try:
        seen = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"survey reply was not valid JSON: {response.text[:200]!r}") from exc
    if not isinstance(seen, dict):
        raise ValueError(f"expected a JSON object, got {type(seen).__name__}")
    return {field: [str(v) for v in seen.get(field, [])] for field in FIELDS}


def count_terms(observations: list[dict]) -> dict[str, Counter]:
    """How many clips each normalised term appears in - not how many times."""
    counts = {field: Counter() for field in FIELDS}
    for observation in observations:
        for field in FIELDS:
            # Normalising first is what makes the count meaningful; the set
            # then collapses repeats within a single clip.
            counts[field].update(set(normalize_terms(observation.get(field, []))))
    return counts


def propose_vocabulary(
    observations: list[dict], min_clips: int = MIN_CLIPS
) -> ProjectVocabulary:
    """The terms that recur often enough to be worth a column.

    Scenes stay empty: unscripted footage has no scene numbers, and inventing
    them would put values in the agent's prompt that no row can carry.
    """
    counts = count_terms(observations)
    kept = {
        field: [term for term, n in counts[field].most_common() if n >= min_clips]
        for field in FIELDS
    }
    return ProjectVocabulary(**kept, scenes=[])


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    import time

    from dotenv import load_dotenv
    from google import genai

    from ingest import upload

    load_dotenv()
    client = genai.Client()

    videos = sorted(Path(sys.argv[1]).glob("*.mp4"))
    if not videos:
        print(f"no .mp4 files in {sys.argv[1]}", file=sys.stderr)
        return 1

    chosen = sample_evenly(videos, int(sys.argv[2]) if len(sys.argv) > 2 else 8)
    print(f"surveying {len(chosen)} of {len(videos)} clips", file=sys.stderr)

    observations = []
    for index, video in enumerate(chosen, start=1):
        print(f"[{index}/{len(chosen)}] {video.name}", file=sys.stderr, flush=True)
        try:
            start = time.perf_counter()
            # Sequential on purpose: each clip sees what the ones before it
            # named, so the same subject keeps the same description.
            seen_so_far = {f: list(count_terms(observations)[f]) for f in FIELDS}
            observations.append(
                observe_clip(upload(video, client), client, known=seen_so_far)
            )
            print(f"    {time.perf_counter() - start:.0f}s", file=sys.stderr)
        except Exception as error:
            print(f"    FAILED: {type(error).__name__}: {error}", file=sys.stderr)

    if not observations:
        print("every clip failed - nothing to propose", file=sys.stderr)
        return 1

    counts = count_terms(observations)
    proposed = propose_vocabulary(observations)

    # Everything seen goes in the report, kept or not, with its clip count.
    # The threshold is a guess; the human deciding needs to see the near
    # misses to know whether it was the right one.
    print(json.dumps({
        "surveyed": [v.name for v in chosen],
        "proposed": {f: getattr(proposed, f) for f in FIELDS},
        "all_terms_by_clip_count": {
            f: dict(counts[f].most_common()) for f in FIELDS
        },
    }, indent=2))

    kept = sum(len(getattr(proposed, f)) for f in FIELDS)
    seen = sum(len(counts[f]) for f in FIELDS)
    print(f"proposed {kept} of {seen} terms seen "
          f"(threshold: {MIN_CLIPS}+ clips). Review, edit, then save as "
          f"assets/vocabulary.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
