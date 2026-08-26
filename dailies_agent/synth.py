"""Synthetic dailies, so the query path can be demonstrated at archive scale.

A real corpus proves the logging is good; this proves the search holds up over
millions of rows. Say so in the demo - a disclosed synthetic benchmark is
respected, a discovered one is not.

Structure matters more than volume here. A scene id already encodes the
camera setup - "14B" is scene 14, setup B - so a setup is planned once
(location, cast, framing) and only the take number, the duration and the
mistakes vary. Each take is its own clip file, as it is on a real camera roll.

    python synth.py 2000000 > shots.jsonl
"""

import json
import random
import sys
from typing import Iterator

import dataclasses

from .vocab import CRAFT_VOCAB, VOCABULARY_CACHE, ProjectVocabulary, load_vocabulary

TAKES_PER_VISIT = (1, 9)
SHOT_SECONDS = (4.0, 95.0)
SLATE_SECONDS = (1.5, 8.0)   # clip starts on the slate, not on "action"
FLAW_RATE = 0.18

_FLAWS = [f for f in CRAFT_VOCAB["quality_flags"] if f != "none"]
_LINES = [
    "You kept it.", "That is not what I said.", "Where were you?",
    "It was always going to end like this.", "Just sign it.", "",
]


def _plan_scene(scene: str, vocabulary: ProjectVocabulary, rng: random.Random) -> dict:
    """Everything a setup fixes: it is one camera position on one scene."""
    cast = vocabulary.characters or ["unknown"]
    return {
        "shot_size": rng.choice(CRAFT_VOCAB["shot_size"]),
        "camera_movement": rng.choice(CRAFT_VOCAB["camera_movement"]),
        "location": rng.choice(vocabulary.locations or ["unknown"]),
        "int_ext": rng.choice(["interior", "exterior"]),
        "time_of_day": rng.choice(CRAFT_VOCAB["time_of_day"]),
        "characters": rng.sample(cast, rng.randint(1, min(3, len(cast)))),
        "props": (
            rng.sample(vocabulary.props, rng.randint(0, min(2, len(vocabulary.props))))
            if vocabulary.props else []
        ),
    }


def demo_vocabulary(project_id: str = "notld_1968") -> ProjectVocabulary:
    """The archive's vocabulary: one screenplay's words, many productions' scenes.

    Characters, locations and props come from the parsed screenplay so the
    synthetic filler and the real logged clips speak the same language, and
    the agent only has to be told one set of values.

    Scene ids stay synthetic and production-prefixed ("P07-14B") because two
    million clips is a studio archive, not one shoot - a feature's dailies
    run to a few thousand. Without that spread the table holds a hundred
    distinct setups and every specific filter returns nothing.
    """
    base = load_vocabulary(project_id=project_id)
    return dataclasses.replace(base, scenes=[
        f"P{p:02d}-{n}{s}"
        for p in range(1, 41)
        for n in range(1, 40)
        for s in ("", "A", "B")
    ])


def generate_rows(
    vocabulary: ProjectVocabulary, count: int, seed: int = 0
) -> Iterator[dict]:
    """Yield exactly `count` plausible shot rows."""
    rng = random.Random(seed)
    scenes = vocabulary.scenes or ["unknown"]
    plans: dict[str, dict] = {}
    takes: dict[str, int] = {}
    produced = clip = visit = 0

    while produced < count:
        scene = scenes[visit % len(scenes)]
        plan = plans.setdefault(scene, _plan_scene(scene, vocabulary, rng))
        visit += 1

        for _ in range(rng.randint(*TAKES_PER_VISIT)):
            if produced >= count:
                return
            takes[scene] = takes.get(scene, 0) + 1
            clip += 1
            start = round(rng.uniform(*SLATE_SECONDS), 1)
            yield {
                "source_file": f"gs://dailies/A{clip // 999 + 1:03d}_C{clip % 999:04d}.mp4",
                "project_id": "archive",
                "scene": scene,
                "take": takes[scene],
                "start_seconds": start,
                "end_seconds": round(start + rng.uniform(*SHOT_SECONDS), 1),
                "shot_size": plan["shot_size"],
                "camera_movement": plan["camera_movement"],
                "location": plan["location"],
                "int_ext": plan["int_ext"],
                "time_of_day": plan["time_of_day"],
                "characters": plan["characters"],
                "props": plan["props"],
                "quality_flags": (
                    [rng.choice(_FLAWS)] if rng.random() < FLAW_RATE else ["none"]
                ),
                "dialogue": rng.choice(_LINES),
                "action": f"{plan['characters'][0]} in the {plan['location'].lower()}.",
                "continuity": "; ".join(
                    f"{name} as established" for name in plan["characters"]
                ),
            }
            produced += 1


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    vocabulary = demo_vocabulary()
    for row in generate_rows(vocabulary, int(sys.argv[1])):
        # JSONEachLine is ClickHouse's native bulk format.
        sys.stdout.write(json.dumps(row) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
