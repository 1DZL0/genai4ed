"""Where a pupil is among a lesson's steps, read from their learning state.

Each entry of `LearningState.steps` is a small record of one step: its judgment, the attempts
and help counted on it, and, once the pupil moves between steps, `parked` (left unfinished),
`wrong` (wrong tries, restored on return), `left` (they moved away from it themselves),
`returns` (times they came back to it after finishing it), `changed` (a later answer replaced
the judgment), `skipped` (the teacher moved them on without a met answer) and `arrived` (how
they just reached it, told to the tutor once).
"""

from app.enums import Judgment, LearningStatus, MessageRole


def padded(steps: list | None, count: int) -> list[dict]:
    """A copy of the step records, one per step of the lesson."""
    rows = [dict(s or {}) for s in (steps or [])]
    while len(rows) < count:
        rows.append({"judgment": None, "attempts": 0, "task": None})
    return rows[: max(count, len(rows))]


def is_done(row: dict | None) -> bool:
    row = row or {}
    return row.get("judgment") == Judgment.MET.value or bool(row.get("skipped"))


def done_steps(rows: list[dict]) -> set[int]:
    return {i for i, r in enumerate(rows) if is_done(r)}


def opened(rows: list[dict], index: int, current: int) -> bool:
    """They have been on this step. Before moving existed, every step up to the current one."""
    row = rows[index] if index < len(rows) else {}
    return (
        index <= current or "since" in row or bool(row.get("judgment")) or bool(row.get("parked"))
    )


def moved_around(rows: list[dict]) -> bool:
    """The pupil has moved between steps themselves at least once."""
    return any(r.get("left") for r in rows)


def reachable(state, rows: list[dict], *, free: bool) -> list[bool]:
    """Which steps a pupil may go to now. Freely: any. In order: the ones they have been on,
    and the first step they have not reached yet."""
    count = len(rows)
    current = state.step_index
    if free or state.status == LearningStatus.COMPLETED.value:
        return [True] * count
    first_new = next(
        (
            i
            for i in range(count)
            if i != current and not is_done(rows[i]) and not opened(rows, i, current)
        ),
        None,
    )
    return [i == current or opened(rows, i, current) or i == first_new for i in range(count)]


def by_step(messages: list) -> list[tuple[object, int]]:
    """Each message with the step it belongs to. A tutor reply carries the step it was written
    on (the one the pupil then answers); a pupil's message carries its own, or, in older
    records, the step of the reply before it."""
    out = []
    current = 0
    for m in messages:
        data = m.data or {}
        if m.role == MessageRole.AGENT.value:
            if isinstance(data.get("step_index"), int):
                current = data["step_index"]
            out.append((m, current))
        else:
            step = data.get("step_index")
            out.append((m, step if isinstance(step, int) else current))
    return out
