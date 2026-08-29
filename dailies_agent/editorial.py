"""Deterministic clip/take ranking for the query agent.

The LLM should interpret intent and explain results; Python scores evidence
from ClickHouse rows so ranking stays grounded and repeatable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

TABLE = "shots"
REAL_FOOTAGE = "source_file NOT LIKE 'gs://%%'"


class RankingProfile(str, Enum):
    BALANCED = "balanced"
    EMOTIONAL = "emotional"
    DIALOGUE = "dialogue"
    ESTABLISHING = "establishing"

    @classmethod
    def parse(cls, value: str | None) -> RankingProfile:
        if not value:
            return cls.BALANCED
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.BALANCED


WEIGHTS: dict[RankingProfile, dict[str, float]] = {
    RankingProfile.BALANCED: {
        "character": 0.25,
        "time": 0.15,
        "keyword": 0.25,
        "dialogue": 0.15,
        "shot_size": 0.05,
        "quality": 0.10,
        "duration": 0.05,
    },
    RankingProfile.EMOTIONAL: {
        "character": 0.30,
        "time": 0.15,
        "keyword": 0.35,
        "dialogue": 0.10,
        "shot_size": 0.00,
        "quality": 0.05,
        "duration": 0.05,
    },
    RankingProfile.DIALOGUE: {
        "character": 0.20,
        "time": 0.10,
        "keyword": 0.10,
        "dialogue": 0.45,
        "shot_size": 0.00,
        "quality": 0.10,
        "duration": 0.05,
    },
    RankingProfile.ESTABLISHING: {
        "character": 0.10,
        "time": 0.20,
        "keyword": 0.10,
        "dialogue": 0.05,
        "shot_size": 0.35,
        "quality": 0.15,
        "duration": 0.05,
    },
}

ESTABLISHING_SIZES = {"extreme_wide", "wide", "medium_wide"}


@dataclass
class SearchCriteria:
    characters: list[str] = field(default_factory=list)
    time_of_day: list[str] = field(default_factory=list)
    int_ext: list[str] = field(default_factory=list)
    location: str | None = None
    shot_size: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def _norm_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [v.strip() for v in values if v and v.strip()]


def _keyword_variants(word: str) -> list[str]:
    w = word.casefold()
    variants = {w}
    if w.endswith("ing") and len(w) > 4:
        root = w[:-3]
        variants.update({root, f"{root}ies", f"{root}ed", f"{root}s"})
    return list(variants)


def _keyword_hits(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    hay = text.casefold()
    hits = 0
    for keyword in keywords:
        if any(variant in hay for variant in _keyword_variants(keyword)):
            hits += 1
    return hits / len(keywords)


def _character_match(found: list[str], wanted: list[str]) -> float:
    if not wanted:
        return 1.0
    if not found:
        return 0.0
    found_cf = {name.casefold() for name in found if name.casefold() != "unknown"}
    if not found_cf:
        return 0.0
    wanted_cf = {name.casefold() for name in wanted}
    return len(found_cf & wanted_cf) / len(wanted_cf)


def _quality_score(flags: list[str]) -> float:
    if not flags:
        return 0.7
    if len(flags) == 1 and flags[0] == "none":
        return 1.0
    penalty = sum(0.15 for flag in flags if flag != "none")
    return max(0.0, 1.0 - penalty)


def _duration_score(start: float, end: float) -> float:
    seconds = max(0.0, float(end) - float(start))
    if seconds <= 0:
        return 0.0
    # Enough coverage to judge, without rewarding extremely long slates.
    return min(1.0, seconds / 8.0)


def _shot_size_score(shot_size: str, profile: RankingProfile) -> float:
    if profile != RankingProfile.ESTABLISHING:
        return 1.0
    return 1.0 if shot_size in ESTABLISHING_SIZES else 0.3


def score_take(
    row: dict[str, Any],
    criteria: SearchCriteria,
    profile: RankingProfile = RankingProfile.BALANCED,
) -> float:
    """Score one shot row against search criteria and a ranking profile."""
    weights = WEIGHTS[profile]
    action = row.get("action") or ""
    dialogue = row.get("dialogue") or ""
    keyword_text = f"{action} {dialogue}"

    parts = {
        "character": _character_match(row.get("characters") or [], criteria.characters),
        "time": 1.0
        if not criteria.time_of_day
        else (1.0 if row.get("time_of_day") in criteria.time_of_day else 0.0),
        "keyword": _keyword_hits(keyword_text, criteria.keywords),
        "dialogue": _keyword_hits(dialogue, criteria.keywords)
        if criteria.keywords
        else (1.0 if dialogue.strip() else 0.2),
        "shot_size": _shot_size_score(row.get("shot_size") or "", profile),
        "quality": _quality_score(row.get("quality_flags") or []),
        "duration": _duration_score(row.get("start_seconds", 0), row.get("end_seconds", 0)),
    }
    return round(sum(weights[name] * parts[name] for name in weights), 4)


def _evidence_for(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "characters": list(row.get("characters") or []),
        "time_of_day": row.get("time_of_day"),
        "shot_size": row.get("shot_size"),
        "action": row.get("action") or "",
        "dialogue": row.get("dialogue") or "",
        "quality_flags": list(row.get("quality_flags") or []),
    }


def _confidence(score: float, runner_up: float | None) -> str:
    margin = score - (runner_up or 0.0)
    if score >= 0.85 and margin >= 0.05:
        return "high"
    if score >= 0.65:
        return "moderate"
    return "low"


def build_clip_summary(
    clip: str,
    ranked_takes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize ranked takes for one clip file."""
    if not ranked_takes:
        raise ValueError(f"no ranked takes for {clip}")
    best = ranked_takes[0]
    alternatives = [
        {"take": item["take"], "score": item["score"]}
        for item in ranked_takes[1:4]
    ]
    return {
        "clip": clip,
        "matching_takes": [item["take"] for item in ranked_takes],
        "best_take": best["take"],
        "score": best["score"],
        "confidence": _confidence(best["score"], ranked_takes[1]["score"] if len(ranked_takes) > 1 else None),
        "evidence": best["evidence"],
        "alternatives": alternatives,
    }


def summarize_clip_takes(
    rows: list[dict[str, Any]],
    criteria: SearchCriteria,
    profile: RankingProfile = RankingProfile.BALANCED,
) -> list[dict[str, Any]]:
    """Group shot rows by clip and pick the best take in each."""
    by_clip: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_clip.setdefault(row["source_file"], []).append(row)

    summaries: list[dict[str, Any]] = []
    for clip, clip_rows in sorted(by_clip.items()):
        best_by_take: dict[int, dict[str, Any]] = {}
        for row in clip_rows:
            take = int(row["take"])
            scored = {
                "take": take,
                "score": score_take(row, criteria, profile),
                "evidence": _evidence_for(row),
            }
            previous = best_by_take.get(take)
            if previous is None or scored["score"] > previous["score"]:
                best_by_take[take] = scored
        ranked = sorted(best_by_take.values(), key=lambda item: (-item["score"], item["take"]))
        summaries.append(build_clip_summary(clip, ranked))
    summaries.sort(key=lambda item: (-item["score"], item["clip"]))
    return summaries


def _clip_ref(clip: dict[str, Any]) -> dict[str, Any]:
    evidence = clip.get("evidence") or {}
    return {
        "clip": clip.get("clip"),
        "best_take": clip.get("best_take"),
        "score": clip.get("score"),
        "confidence": clip.get("confidence"),
        "action": (evidence.get("action") or "")[:200],
    }


def _weakness(clip: dict[str, Any]) -> str:
    evidence = clip.get("evidence") or {}
    action = (evidence.get("action") or "").casefold()
    if "laugh" in action and any(word in action for word in ("cry", "crying", "cries")):
        return (
            "action describes laughing while someone is crying — character/"
            "time metadata match, but the emotional intent conflicts"
        )
    names = [n.casefold() for n in (evidence.get("characters") or [])]
    prose_names = sum(1 for n in names if n != "unknown" and n in action)
    if names and prose_names == 0:
        return (
            "characters are tagged in metadata but not named in the action"
            " description — treat as weaker evidence"
        )
    return "lowest score in this set; prefer the strongest clip unless the editor needs this coverage"


def critique_ranking(clips: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic answer for 'are you sure?' — the model should relay this."""
    if not clips:
        return {
            "do_not_increase_confidence": True,
            "challenge_answer": "No ranking is stored. Run rank_clips first.",
        }
    strongest = clips[0]
    alternative = clips[1] if len(clips) > 1 else None
    weakest = clips[-1]
    weakness = _weakness(weakest)
    alt_line = (
        f"{alternative['clip']} is a strong alternative (score {alternative['score']}). "
        if alternative
        else ""
    )
    answer = (
        f"Not completely. {strongest['clip']} is the strongest match "
        f"(score {strongest['score']}, {strongest.get('confidence')}). "
        f"{alt_line}"
        f"{weakest['clip']} is the weakest: {weakness.rstrip('. ')}."
    )
    return {
        "do_not_increase_confidence": True,
        "strongest": _clip_ref(strongest),
        "strong_alternative": _clip_ref(alternative) if alternative else None,
        "weakest": _clip_ref(weakest),
        "weakness": weakness,
        "challenge_answer": answer,
    }


def rank_takes(
    rows: list[dict[str, Any]],
    criteria: SearchCriteria,
    profile: RankingProfile = RankingProfile.BALANCED,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return the top clips with best take, evidence, and alternatives."""
    return summarize_clip_takes(rows, criteria, profile)[: max(1, limit)]


def _where_clause(criteria: SearchCriteria) -> tuple[str, dict[str, Any]]:
    clauses = [REAL_FOOTAGE]
    params: dict[str, Any] = {}
    for index, character in enumerate(criteria.characters):
        key = f"char_{index}"
        clauses.append(f"has(characters, %({key})s)")
        params[key] = character
    if criteria.time_of_day:
        clauses.append("time_of_day IN %(times)s")
        params["times"] = tuple(criteria.time_of_day)
    if criteria.int_ext:
        clauses.append("int_ext IN %(int_ext)s")
        params["int_ext"] = tuple(criteria.int_ext)
    if criteria.location:
        clauses.append("location = %(location)s")
        params["location"] = criteria.location
    if criteria.shot_size:
        clauses.append("shot_size IN %(shot_sizes)s")
        params["shot_sizes"] = tuple(criteria.shot_size)
    for index, keyword in enumerate(criteria.keywords):
        key = f"kw_{index}"
        clauses.append(
            f"(action ILIKE concat('%%', %({key})s, '%%')"
            f" OR dialogue ILIKE concat('%%', %({key})s, '%%'))"
        )
        params[key] = keyword
    return " AND ".join(clauses), params


def fetch_matching_shots(
    client,
    project_id: str,
    criteria: SearchCriteria,
    *,
    source_file: str | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Load candidate shot rows from ClickHouse for ranking."""
    where, params = _where_clause(criteria)
    params["pid"] = project_id
    clauses = [f"project_id = %(pid)s", where]
    if source_file:
        clauses.append("source_file = %(source_file)s")
        params["source_file"] = source_file
    sql = (
        f"SELECT source_file, take, characters, time_of_day, int_ext, location,"
        f" scene, shot_size, quality_flags, start_seconds, end_seconds,"
        f" action, dialogue, continuity"
        f" FROM {TABLE} WHERE {' AND '.join(clauses)}"
        f" ORDER BY source_file, take LIMIT {int(limit)}"
    )
    result = client.query(sql, parameters=params)
    columns = result.column_names
    return [dict(zip(columns, row)) for row in result.result_rows]


def query_and_rank(
    client,
    project_id: str,
    criteria: SearchCriteria,
    profile: RankingProfile = RankingProfile.BALANCED,
    *,
    limit: int = 3,
    source_file: str | None = None,
) -> list[dict[str, Any]]:
    rows = fetch_matching_shots(
        client, project_id, criteria, source_file=source_file
    )
    return rank_takes(rows, criteria, profile, limit=limit)
