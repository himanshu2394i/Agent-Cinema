"""Group consecutive camera clips into story sequences.

Screenplay scene ids are often `unknown` on real footage, so the coverage
plan itself is the timeline: A001_C0064 then C0065 is one stretch of the
film. This module clusters matching shots by that order and summarizes the
stretch so the agent can talk about scenes, not isolated rows.
"""

from __future__ import annotations

import re
from typing import Any

from .editorial import _character_match, _keyword_hits

CLIP_RE = re.compile(r"A\d+_C(\d+)\.mp4$", re.IGNORECASE)

EMOTION_CUES = (
    "crying",
    "cries",
    "smile",
    "smiling",
    "laugh",
    "angry",
    "fear",
    "kiss",
    "embrace",
    "holds",
    "refuse",
    "refuses",
    "wait",
    "waits",
)


def clip_index(source_file: str) -> int | None:
    """Camera-roll clip number, or None for synthetic gs:// rows."""
    if source_file.startswith("gs://"):
        return None
    name = source_file.rsplit("/", 1)[-1]
    match = CLIP_RE.search(name)
    if not match:
        return None
    return int(match.group(1))


def neighbor_range(after_clip: int, count: int = 3) -> tuple[int, int]:
    return after_clip + 1, after_clip + max(1, count)


def _clip_blob(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    takes = sorted({int(r["take"]) for r in rows})
    actions = []
    dialogues = []
    continuity = []
    characters: list[str] = []
    seen_char: set[str] = set()
    for row in rows:
        for name in row.get("characters") or []:
            key = name.casefold()
            if key in {"", "unknown"} or key in seen_char:
                continue
            seen_char.add(key)
            characters.append(name)
        action = (row.get("action") or "").strip()
        if action and action not in actions:
            actions.append(action)
        line = (row.get("dialogue") or "").strip()
        if line and line not in dialogues:
            dialogues.append(line)
        note = (row.get("continuity") or "").strip()
        if note and note not in continuity:
            continuity.append(note)
    return {
        "clip": first["source_file"],
        "index": clip_index(first["source_file"]),
        "takes": takes,
        "characters": characters,
        "actions": actions[:4],
        "dialogues": dialogues[:3],
        "continuity": continuity[:2],
        "time_of_day": first.get("time_of_day"),
        "location": first.get("location"),
        "scene": first.get("scene"),
    }


def group_consecutive_clips(
    rows: list[dict[str, Any]],
    max_gap: int = 1,
) -> list[dict[str, Any]]:
    """Cluster matching rows into runs of nearby clip numbers."""
    by_file: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if clip_index(row["source_file"]) is None:
            continue
        by_file.setdefault(row["source_file"], []).append(row)

    ordered = sorted(by_file.items(), key=lambda item: clip_index(item[0]) or 0)
    sequences: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    last_index: int | None = None
    for source, clip_rows in ordered:
        index = clip_index(source)
        blob = _clip_blob(clip_rows)
        if last_index is None or index is None or index - last_index <= max_gap + 1:
            current.append(blob)
        else:
            sequences.append(current)
            current = [blob]
        last_index = index
    if current:
        sequences.append(current)

    out = []
    for clips in sequences:
        first = clips[0]["index"]
        last = clips[-1]["index"]
        out.append(
            {
                "scene_id": f"C{first:04d}-C{last:04d}",
                "start_clip": first,
                "end_clip": last,
                "clips": clips,
            }
        )
    return out


def _emotional_arc(clips: list[dict[str, Any]]) -> str:
    hits: list[str] = []
    for clip in clips:
        text = " ".join(clip.get("actions") or []).casefold()
        for cue in EMOTION_CUES:
            if cue in text and cue not in hits:
                hits.append(cue)
    if not hits:
        first = (clips[0].get("actions") or ["unspecified action"])[0]
        last = (clips[-1].get("actions") or [first])[0]
        if first == last:
            return first[:160]
        return f"{first[:80]} → {last[:80]}"
    return " → ".join(hits)


def _confidence(clips: list[dict[str, Any]], wanted_characters: list[str], keywords: list[str]) -> str:
    named = 0
    keyword_score = 0.0
    for clip in clips:
        named += _character_match(clip.get("characters") or [], wanted_characters) if wanted_characters else 1.0
        blob = " ".join((clip.get("actions") or []) + (clip.get("dialogues") or []))
        keyword_score += _keyword_hits(blob, keywords) if keywords else 1.0
    n = max(1, len(clips))
    char_avg = named / n
    key_avg = keyword_score / n
    if char_avg >= 0.8 and key_avg >= 0.5:
        return "high"
    if char_avg >= 0.4 or key_avg >= 0.3:
        return "moderate"
    return "low"


TIER_RANK = {"DIRECT_INTERACTION": 0, "CONTEXTUAL": 1, "METADATA_ONLY": 2}


def interaction_tier(prose: str, wanted_characters: list[str]) -> str:
    """How strongly the prose (not just the characters array) supports the pair."""
    text = (prose or "").casefold()
    if not wanted_characters:
        return "DIRECT_INTERACTION" if text.strip() else "METADATA_ONLY"
    hits = [name for name in wanted_characters if name.casefold() in text]
    if len(hits) >= min(2, len(wanted_characters)):
        return "DIRECT_INTERACTION"
    if len(wanted_characters) == 1 and hits:
        return "DIRECT_INTERACTION"
    related = ("father", "baba", "wedding", "mother", "kasam")
    if hits or any(word in text for word in related):
        return "CONTEXTUAL"
    return "METADATA_ONLY"


def summarize_sequence(
    sequence: dict[str, Any],
    *,
    wanted_characters: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    clips = sequence["clips"]
    characters: list[str] = []
    seen: set[str] = set()
    actions: list[str] = []
    dialogues: list[str] = []
    continuity: list[str] = []
    takes: list[int] = []
    for clip in clips:
        takes.extend(clip.get("takes") or [])
        for name in clip.get("characters") or []:
            if name.casefold() not in seen:
                seen.add(name.casefold())
                characters.append(name)
        for action in clip.get("actions") or []:
            if action not in actions:
                actions.append(action)
        for line in clip.get("dialogues") or []:
            if line not in dialogues:
                dialogues.append(line)
        for note in clip.get("continuity") or []:
            if note not in continuity:
                continuity.append(note)
    return {
        "scene_id": sequence["scene_id"],
        "start_clip": sequence["start_clip"],
        "end_clip": sequence["end_clip"],
        "clips": [c["clip"] for c in clips],
        "clip_count": len(clips),
        "takes": sorted(set(takes)),
        "characters": characters,
        "dialogue_summary": " | ".join(line[:120] for line in dialogues[:4]),
        "actions": actions[:6],
        "emotional_arc": _emotional_arc(clips),
        "continuity_notes": continuity[:4],
        "time_of_day": clips[0].get("time_of_day"),
        "location": clips[0].get("location"),
        "confidence": _confidence(clips, wanted_characters or [], keywords or []),
        "evidence_tier": interaction_tier(
            " ".join(actions + dialogues),
            wanted_characters or [],
        ),
    }


def chronological_after(
    anchor: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Next sequence whose first clip is after the anchor's last clip."""
    end = anchor.get("end_clip")
    if end is None:
        return None
    later = [item for item in timeline if (item.get("start_clip") or 0) > end]
    later.sort(key=lambda item: item.get("start_clip") or 0)
    return later[0] if later else None


def investigate_from_rows(
    rows: list[dict[str, Any]],
    *,
    characters: list[str] | None = None,
    event: str | None = None,
    max_gap: int = 1,
    max_sequences: int = 8,
) -> dict[str, Any]:
    """Build a scene map from matching shot rows."""
    keywords = [part for part in (event or "").replace(",", " ").split() if part]
    wanted = characters or []
    grouped = group_consecutive_clips(rows, max_gap=max_gap)
    timeline = [
        summarize_sequence(seq, wanted_characters=wanted, keywords=keywords)
        for seq in grouped
    ]
    timeline.sort(key=lambda item: item.get("start_clip") or 0)

    def relevance(item: dict[str, Any]) -> tuple:
        prose = " ".join(item.get("actions") or []) + " " + (item.get("dialogue_summary") or "")
        return (
            TIER_RANK.get(item.get("evidence_tier") or "METADATA_ONLY", 9),
            -_keyword_hits(prose, keywords) if keywords else 0,
            item.get("start_clip") or 0,
        )

    # Relevance picks *which* sequences make the cut when there are more than
    # there is room for; the story itself still reads front to back. Each item
    # keeps its evidence_tier so weak matches can be flagged in place rather
    # than hidden by being sorted to the bottom.
    displayed = sorted(
        sorted(timeline, key=relevance)[:max_sequences],
        key=lambda item: item.get("start_clip") or 0,
    )
    if keywords:
        anchor = min(timeline, key=lambda item: (
            -_keyword_hits(
                " ".join(item.get("actions") or []) + " " + (item.get("dialogue_summary") or ""),
                keywords,
            ),
            item.get("start_clip") or 0,
        ))
    else:
        anchor = displayed[0] if displayed else None
    after = chronological_after(anchor, timeline) if anchor else None
    return {
        "sequence_count": len(timeline),
        "sequences": displayed,
        "anchor": anchor,
        "after": after,
        "note": (
            "Sequences are consecutive camera clips (coverage order), not"
            " numbered screenplay scenes — real footage often has scene='unknown'."
            " Sequences read in shooting order; evidence_tier on each says how"
            " strongly it supports the question."
            " `after` is the next sequence by clip number, not by relevance."
            " evidence_tier: DIRECT_INTERACTION > CONTEXTUAL > METADATA_ONLY."
        ),
    }


def chronological_coverage(
    rows: list[dict[str, Any]],
    start_clip: int,
    end_clip: int,
    *,
    wanted_characters: list[str] | None = None,
) -> dict[str, Any]:
    """Literal clip-by-clip coverage of a range, in shooting order.

    Unlike `investigate_from_rows` this does no relevance ranking and no
    grouping: it answers "what is actually on C0101 through C0108", which is
    the question a filtered character search can never answer.
    """
    wanted = wanted_characters or []
    by_file: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        index = clip_index(row["source_file"])
        if index is None or not start_clip <= index <= end_clip:
            continue
        by_file.setdefault(row["source_file"], []).append(row)

    clips = []
    for source in sorted(by_file, key=lambda f: clip_index(f) or 0):
        blob = _clip_blob(by_file[source])
        prose = " ".join((blob.get("actions") or []) + (blob.get("dialogues") or []))
        clips.append(
            {
                "clip": blob["clip"],
                "clip_label": f"C{blob['index']:04d}",
                "takes": blob["takes"],
                "characters": blob["characters"],
                "actions": blob["actions"],
                "dialogue_summary": " | ".join(line[:120] for line in blob["dialogues"]),
                "time_of_day": blob.get("time_of_day"),
                "location": blob.get("location"),
                "evidence_tier": interaction_tier(prose, wanted),
            }
        )

    present = {c["clip_label"] for c in clips}
    return {
        "range": f"C{start_clip:04d}-C{end_clip:04d}",
        "clips": clips,
        "clip_count": len(clips),
        "missing_clips": [
            f"C{n:04d}" for n in range(start_clip, end_clip + 1)
            if f"C{n:04d}" not in present
        ],
        "note": (
            "Literal coverage order for the requested range - not relevance"
            " ranked and not filtered by character. missing_clips have no"
            " ingested footage in this project."
        ),
    }
