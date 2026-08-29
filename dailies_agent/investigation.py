"""The evidence ledger: what the agent has looked at, and what it still owes.

ADK's LlmAgent already loops - model, tool, model, tool - so this is not a
scheduler. It is the memory that loop lacks. Every editorial tool records
what it saw; `review` reads that back and answers one question
deterministically: is there a stretch of footage we claimed something about
without actually looking at it?

Only observable state goes in a step: the tool, the question, the clips seen,
the finding. Not the model's reasoning - that is neither checkable nor
citable.
"""

from __future__ import annotations

from typing import Any

from .scene import clip_index

# The runtime ceiling (max_llm_calls) is not an investigation policy. Five
# steps covers anchor -> timeline -> gap -> cross-check -> answer.
MAX_INVESTIGATION_STEPS = 5


def clip_label(clip: int | str) -> str | None:
    """`C0101` from a clip number or a source filename, or None if unnumbered."""
    if isinstance(clip, int):
        return f"C{clip:04d}"
    index = clip_index(str(clip))
    return None if index is None else f"C{index:04d}"


def record(
    ledger: list[dict[str, Any]],
    *,
    tool: str,
    question: str,
    clips_seen: list[str] | None = None,
    finding: str = "",
    evidence_tier: str | None = None,
    pending_followup: list[int] | None = None,
    invocation: str | None = None,
) -> dict[str, Any]:
    """Append one investigation step and return it.

    `pending_followup` is an inclusive [start, end] clip range this step
    raised but did not examine - the debt `review` collects on.
    """
    step = {
        "step": len(ledger) + 1,
        "tool": tool,
        "question": question,
        "clips_seen": [c for c in (clips_seen or []) if c],
        "finding": finding,
        "evidence_tier": evidence_tier,
        "invocation": invocation,
    }
    if pending_followup:
        step["pending_followup"] = list(pending_followup)
    ledger.append(step)
    return step


def review(
    ledger: list[dict[str, Any]] | None,
    invocation: str | None = None,
) -> dict[str, Any]:
    """Is the evidence sufficient, and if not, which clips are missing?

    The budget is per question, not per session: a long conversation must not
    leave the tenth question with nothing left to spend. `invocation` scopes
    the ledger to the turn being answered; the rest stays stored for the trace.
    """
    steps = list(ledger or [])
    if invocation is not None:
        steps = [s for s in steps if s.get("invocation") == invocation]
    remaining = max(0, MAX_INVESTIGATION_STEPS - len(steps))
    seen: set[str] = set()
    for step in steps:
        seen.update(step.get("clips_seen") or [])

    missing: list[str] = []
    for step in steps:
        followup = step.get("pending_followup")
        if not followup:
            continue
        start, end = int(followup[0]), int(followup[-1])
        wanted = [f"C{n:04d}" for n in range(start, end + 1)]
        gap = [name for name in wanted if name not in seen]
        if gap:
            missing = gap
            break

    verdict = {
        "steps": steps,
        "step_count": len(steps),
        "remaining_budget": remaining,
        "budget_exhausted": remaining == 0,
        "clips_seen": sorted(seen),
        "sufficient": not missing,
        "gap": "chronological_followup_unchecked" if missing else None,
        "missing_clips": missing,
        "recommended_action": "inspect_clips" if missing else None,
    }
    if missing and remaining == 0:
        # Out of budget with a hole still in the evidence: say so rather than
        # investigating past the limit or pretending the hole is closed.
        verdict["recommended_action"] = "answer_with_uncertainty"
        verdict["note"] = (
            "Investigation budget spent with unchecked footage remaining."
            " Say what is established and name what could not be checked."
        )
    return verdict
