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


def normalize_terms(values: list[str], *, verbatim: bool = False) -> list[str]:
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
            characters=normalize_terms(characters),
            locations=normalize_terms(locations),
            props=normalize_terms(props),
            # Scene ids are slate data. "14B" is not prose; never recase it.
            scenes=normalize_terms(scenes, verbatim=True),
        )

    def enum_of(self, attr: str) -> list[str]:
        """Allowed values for one project field, plus the escape hatch.

        UNKNOWN stops an unrecognised face or object from forcing the model
        into a wrong-but-allowed value just to satisfy the enum.
        """
        return [*getattr(self, attr), UNKNOWN]


# Prefer package-local cache so Cloud Run (ADK only ships dailies_agent/) works.
VOCABULARY_CACHE = Path(__file__).resolve().parent / "assets" / "vocabulary.json"
_LEGACY_VOCABULARY_CACHE = Path("assets/vocabulary.json")


def vocabulary_path_for(project_id: str) -> Path:
    """Path to a project's cached vocabulary, or the legacy default."""
    try:
        from projects import vocabulary_path

        path = vocabulary_path(project_id)
        if path.exists():
            return path
    except ImportError:
        path = Path(f"assets/projects/{project_id}/vocabulary.json")
    if project_id == "notld_1968":
        if VOCABULARY_CACHE.exists():
            return VOCABULARY_CACHE
        if _LEGACY_VOCABULARY_CACHE.exists():
            return _LEGACY_VOCABULARY_CACHE
    return path


def load_vocabulary(
    path: Path | None = None, *, project_id: str = "notld_1968"
) -> ProjectVocabulary:
    """Load a vocabulary parsed earlier from a screenplay.

    Values are already normalised, so this constructs directly rather than
    going through from_raw.
    """
    target = path if path is not None else vocabulary_path_for(project_id)
    if not Path(target).exists():
        raise FileNotFoundError(
            f"No vocabulary at {target}. Upload a screenplay for project"
            f" {project_id!r} first."
        )
    return ProjectVocabulary(**json.loads(Path(target).read_text()))
