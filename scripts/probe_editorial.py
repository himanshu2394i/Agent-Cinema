"""Record what rank_clips actually returns against live ClickHouse.

Does not tune weights. Prints ranked evidence for adversarial editor queries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from dailies_agent.editorial import RankingProfile, SearchCriteria, query_and_rank
from dailies_agent.db_connect import connect

PROJECT = "lailamajnu"

QUERIES = [
    (
        "best Laila+Qays crying at night",
        SearchCriteria(
            characters=["Laila", "Qays"],
            time_of_day=["night"],
            keywords=["crying"],
        ),
        RankingProfile.EMOTIONAL,
        3,
    ),
    (
        "Laila crying with Qays (no time filter)",
        SearchCriteria(characters=["Laila", "Qays"], keywords=["crying"]),
        RankingProfile.EMOTIONAL,
        3,
    ),
    (
        "night or dusk clips (no characters)",
        SearchCriteria(time_of_day=["night", "dusk"]),
        RankingProfile.BALANCED,
        5,
    ),
    (
        "Qays talks about marrying Laila",
        SearchCriteria(characters=["Qays"], keywords=["marry"]),
        RankingProfile.DIALOGUE,
        3,
    ),
    (
        "Laila smiling / happy",
        SearchCriteria(characters=["Laila"], keywords=["smile", "happy"]),
        RankingProfile.EMOTIONAL,
        3,
    ),
    (
        "wide establishing at night",
        SearchCriteria(time_of_day=["night"], shot_size=["wide", "extreme_wide"]),
        RankingProfile.ESTABLISHING,
        3,
    ),
]


def _brief(clip: dict) -> dict:
    evidence = clip.get("evidence") or {}
    return {
        "clip": clip["clip"],
        "best_take": clip["best_take"],
        "score": clip["score"],
        "confidence": clip["confidence"],
        "matching_takes": clip["matching_takes"][:12],
        "take_count": len(clip["matching_takes"]),
        "characters": evidence.get("characters"),
        "time_of_day": evidence.get("time_of_day"),
        "action": (evidence.get("action") or "")[:180],
        "dialogue": (evidence.get("dialogue") or "")[:120],
        "alternatives": clip.get("alternatives"),
    }


def main() -> int:
    client = connect()
    for title, criteria, profile, limit in QUERIES:
        ranked = query_and_rank(client, PROJECT, criteria, profile, limit=limit)
        print("\n==", title, "==")
        print("profile:", profile.value, "returned:", len(ranked))
        print(json.dumps([_brief(c) for c in ranked], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
