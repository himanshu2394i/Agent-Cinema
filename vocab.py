"""Controlled vocabulary for shot logging.

Two layers, deliberately different:

  CRAFT_VOCAB       - how it was shot. Standard cinematographic grammar,
                      identical across every project. Hardcoded.
  ProjectVocabulary - what is in the frame. Derived from the screenplay,
                      different for every project. Never hardcoded.

Both feed the same two consumers: the enum constraints on the ingest call,
and the agent's system prompt. One source of truth keeps the values the
model writes identical to the values the agent filters on.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CRAFT_VOCAB: dict[str, list[str]] = {
    "shot_size": [
        "extreme_wide", "wide", "medium_wide", "medium",
        "medium_close", "close_up", "extreme_close_up", "insert",
    ],
    "camera_movement": [
        "static", "pan", "tilt", "dolly", "tracking",
        "handheld", "crane", "zoom",
    ],
    "time_of_day": [
        "dawn", "morning", "midday", "afternoon",
        "golden_hour", "dusk", "night", "indeterminate",
    ],
    "int_ext": ["interior", "exterior", "indeterminate"],
    "quality_flags": [
        "soft_focus", "boom_in_frame", "camera_shake",
        "exposure_blown", "actor_looks_off_mark", "none",
    ],
}

UNKNOWN = "unknown"

# "SARAH (V.O.)" / "MARCUS (CONT'D)" are screenplay cue decorations, not names.
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
# str.title() mangles possessives: "SARAH'S CAR" -> "Sarah'S Car". Real
# screenplay locations are full of them, so title-case words, not letters.
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


def _titlecase(text: str) -> str:
    return _WORD.sub(lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), text)


def _clean(values: list[str], *, verbatim: bool = False) -> list[str]:
    """Strip cue decorations, normalise, drop blanks, dedupe case-insensitively.

    First spelling encountered wins, so ordering follows the screenplay.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        name = raw if verbatim else _titlecase(_PARENTHETICAL.sub("", raw))
        name = name.strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        out.append(name)
    return out


@dataclass
class ProjectVocabulary:
    """Layer 2 - the words this particular production is allowed to use."""

    characters: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    props: list[str] = field(default_factory=list)
    scenes: list[str] = field(default_factory=list)

    @classmethod
    def from_raw(
        cls,
        characters: list[str],
        locations: list[str],
        props: list[str],
        scenes: list[str],
    ) -> "ProjectVocabulary":
        return cls(
            characters=_clean(characters),
            locations=_clean(locations),
            props=_clean(props),
            # Scene ids are slate data. "14B" is not prose; never recase it.
            scenes=_clean(scenes, verbatim=True),
        )

    def enum_of(self, attr: str) -> list[str]:
        """Allowed values for one project field, plus the escape hatch.

        UNKNOWN stops an unrecognised face or object from forcing the model
        into a wrong-but-allowed value just to satisfy the enum.
        """
        return [*getattr(self, attr), UNKNOWN]


VOCABULARY_CACHE = Path("assets/vocabulary.json")


def load_vocabulary(path: Path = VOCABULARY_CACHE) -> ProjectVocabulary:
    """Load a vocabulary parsed earlier from a screenplay.

    Values are already normalised, so this constructs directly rather than
    going through from_raw.
    """
    if not Path(path).exists():
        raise FileNotFoundError(
            f"No vocabulary at {path}. Run smoke.py against a screenplay first."
        )
    return ProjectVocabulary(**json.loads(Path(path).read_text()))
