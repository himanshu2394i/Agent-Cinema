"""ADK tool wrappers around deterministic editorial ranking."""

from __future__ import annotations

import os
from typing import Any

from .editorial import (
    RankingProfile,
    SearchCriteria,
    critique_ranking,
    fetch_matching_shots,
    query_and_rank,
    rank_takes,
    summarize_clip_takes,
)


def _project(tool_context) -> str:
    return tool_context.state.get("project_id") or os.getenv(
        "PROJECT_ID", "notld_1968"
    )


def _criteria(
    characters: list[str] | None = None,
  time_of_day: list[str] | None = None,
  int_ext: list[str] | None = None,
  location: str | None = None,
  shot_size: list[str] | None = None,
  keywords: list[str] | None = None,
) -> SearchCriteria:
    return SearchCriteria(
        characters=characters or [],
        time_of_day=time_of_day or [],
        int_ext=int_ext or [],
        location=(location or "").strip() or None,
        shot_size=shot_size or [],
        keywords=keywords or [],
    )


def rank_clips(
    characters: list[str] | None = None,
    time_of_day: list[str] | None = None,
    int_ext: list[str] | None = None,
    location: str | None = None,
    shot_size: list[str] | None = None,
    keywords: list[str] | None = None,
    ranking_profile: str = "balanced",
    limit: int = 3,
    tool_context=None,
) -> dict[str, Any]:
    """Find and rank the best matching clips for an editorial question.

    Use this instead of dumping raw SQL rows when the editor asks which clips
    match, or for the best take. Ranking is deterministic in Python.

    Args:
        characters: Character names that should appear, e.g. ['Laila', 'Qays'].
        time_of_day: Craft values such as ['night', 'dusk'].
        int_ext: ['interior'] or ['exterior'] when location type matters.
        location: Exact location name from the screenplay vocabulary.
        shot_size: Craft shot sizes, useful for establishing-shot questions.
        keywords: Words to match in action or dialogue, e.g. ['crying'].
        ranking_profile: balanced, emotional, dialogue, or establishing.
        limit: How many top clips to return (default 3).

    Returns:
        Ranked clips with best_take, score, confidence, evidence, alternatives.
    """
    from .db_connect import connect

    criteria = _criteria(
        characters, time_of_day, int_ext, location, shot_size, keywords
    )
    profile = RankingProfile.parse(ranking_profile)
    ranked = query_and_rank(
        connect(),
        _project(tool_context),
        criteria,
        profile,
        limit=max(1, min(int(limit), 10)),
    )
    from .editorial import critique_ranking

    critique = critique_ranking(ranked)
    payload = {
        "project_id": _project(tool_context),
        "ranking_profile": profile.value,
        "criteria": {
            "characters": criteria.characters,
            "time_of_day": criteria.time_of_day,
            "keywords": criteria.keywords,
            "shot_size": criteria.shot_size,
            "location": criteria.location,
        },
        "clips": ranked,
        "clip_count": len(ranked),
        "critique": critique,
    }
    if tool_context is not None:
        tool_context.state["last_ranking"] = payload
    return payload


def summarize_takes(
    source_file: str,
    characters: list[str] | None = None,
    time_of_day: list[str] | None = None,
    keywords: list[str] | None = None,
    ranking_profile: str = "balanced",
    tool_context=None,
) -> dict[str, Any]:
    """Summarize every matching take inside one clip file.

    Args:
        source_file: Clip filename such as A001_C0123.mp4.
        characters: Optional character filter.
        time_of_day: Optional craft filter.
        keywords: Optional action/dialogue keywords.
        ranking_profile: balanced, emotional, dialogue, or establishing.

    Returns:
        One clip summary with matching_takes, best_take, evidence, alternatives.
    """
    from .db_connect import connect

    criteria = _criteria(characters, time_of_day, keywords=keywords)
    profile = RankingProfile.parse(ranking_profile)
    rows = fetch_matching_shots(
        connect(),
        _project(tool_context),
        criteria,
        source_file=source_file.strip(),
    )
    summaries = summarize_clip_takes(rows, criteria, profile)
    if not summaries:
        return {
            "clip": source_file,
            "error": "no matching takes in this clip for the given filters",
        }
    return summaries[0]


def reassess_last_ranking(tool_context=None) -> dict[str, Any]:
    """Deterministic response when the editor challenges a ranked answer.

    Call this for 'are you sure?' / 'really?' — relay challenge_answer verbatim.
    """
    stored = (tool_context.state or {}).get("last_ranking") if tool_context else None
    if stored and stored.get("critique"):
        note = dict(stored["critique"])
        note["had_prior_ranking"] = True
        return note
    clips = (stored or {}).get("clips") or []
    note = critique_ranking(clips)
    note["had_prior_ranking"] = bool(clips)
    return note


def investigate_scene(
    characters: list[str] | None = None,
    time_of_day: list[str] | None = None,
    event: str | None = None,
    keywords: list[str] | None = None,
    max_sequences: int = 6,
    tool_context=None,
) -> dict[str, Any]:
    """Map matching footage into consecutive clip sequences (story context).

    Use when the editor asks what happens between characters, what comes
    after a moment, or for every interaction — not for a single best take.

    Args:
        characters: People who should appear, e.g. ['Laila', 'Qays'].
        time_of_day: Optional craft filter such as ['night'].
        event: Short prose event, e.g. 'wedding' or 'talks to father'.
        keywords: Extra action/dialogue words to require.
        max_sequences: How many sequences to return (default 6).

    Returns:
        sequences with scene_id, clips, actions, emotional_arc, confidence,
        plus `after` for the next matching stretch on the timeline.
    """
    from .db_connect import connect
    from .editorial import SearchCriteria, fetch_matching_shots
    from .scene import investigate_from_rows

    words = list(keywords or [])
    criteria = SearchCriteria(
        characters=characters or [],
        time_of_day=time_of_day or [],
        keywords=words,
    )
    rows = fetch_matching_shots(
        connect(),
        _project(tool_context),
        criteria,
        limit=4000,
    )
    report = investigate_from_rows(
        rows,
        characters=characters or [],
        event=event,
        max_sequences=max(1, min(int(max_sequences), 12)),
    )
    report["project_id"] = _project(tool_context)
    report["criteria"] = {
        "characters": characters or [],
        "time_of_day": time_of_day or [],
        "event": event,
    }
    return report


def _select_reason(item: dict[str, Any]) -> str:
    if item.get("selection_reason"):
        return str(item["selection_reason"])
    evidence = item.get("evidence") or {}
    action = (evidence.get("action") or "").strip()
    if action:
        return action[:160]
    characters = evidence.get("characters") or []
    if characters:
        return "characters: " + ", ".join(str(c) for c in characters)
    return "ranked match"


def add_to_select_list(
    clips: list[dict[str, Any]],
    tool_context=None,
) -> dict[str, Any]:
    """Add ranked clips/takes to this session's editorial decision record.

    Preserve score, confidence, and why the take was selected — not just
    the filename.

    Args:
        clips: Ranked items from rank_clips / summarize_takes.

    Returns:
        The updated select list and entries added.
    """
    state = tool_context.state
    bucket = state.setdefault("select_list", [])
    added = []
    for item in clips:
        clip = item.get("clip") or item.get("source_file")
        if not clip:
            continue
        entry = {
            "clip": clip,
            "best_take": item.get("best_take") or item.get("take"),
            "ranking_score": item.get("score"),
            "confidence": item.get("confidence"),
            "selection_reason": _select_reason(item),
        }
        bucket.append(entry)
        added.append(entry)
    return {"added": added, "select_list_count": len(bucket)}


def get_select_list(tool_context=None) -> dict[str, Any]:
    """Return the current session select list as an editorial decision record."""
    items = list(tool_context.state.get("select_list", []))
    lines = []
    for item in items:
        lines.append(
            f"{item.get('clip')} / take {item.get('best_take')} — "
            f"score {item.get('ranking_score')} — {item.get('confidence')} — "
            f"{item.get('selection_reason')}"
        )
    return {"select_list": items, "count": len(items), "display": lines}
