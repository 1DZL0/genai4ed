"""A harder question of the tutor's own, for a pupil who is finding the lesson easy.

When the lesson's teacher has switched it on (`harder_questions` in the memory settings), the
tutor may keep a pupil who got a step right first time, with no help, on that step for one
harder question on the same objective before they move on. The step is already theirs. The
extra question gets one try, changes no mark and counts as no wrong try, and the pupil moves on
with the tutor's reply to it whatever they wrote. The try is kept as its own kind of evidence
(`EvidenceKind.HARDER_QUESTION`), apart from the judgments of the lesson's own steps.

On the step's row it is `harder`: `{"question", "open": True}` while the pupil has yet to
answer, then `{"question", "open": False, "judgment"}`, the judgment None when they left it
unanswered. One to a step.

This module holds the rule for when one may be asked, the row's marks and every word the tutor
is told about it; nothing of it reaches the prompt while the switch is off. To take the whole
thing out: leave the switch off, or delete this module and the places that call it, the
`harder_questions` column and the evidence kind (downgrade migration f2a3b4c5d6e7) and
tests/test_harder_question.py. The Settings page no longer shows the switch, so it stays off
until the tutor work replaces it.
"""

from app.enums import Judgment

# Under what is allowed right now, on the turn a pupil's first answer to a step comes in.
OFFER = (
    "A harder question: allowed on this step, once. If what they just wrote meets the finish "
    "line, and this lesson and what you know of them from before show they are finding it "
    "easy, you may keep them here for one harder question of your own before they move on. It "
    "goes deeper into this step's objective (why the method works, a case where it would not, "
    "the same idea somewhere new) and never into a later step. Say what they got right, say "
    'this one is an extra, ask it in full, put it in task, set move to "harder" with your met '
    "assessment, and leave step_done false. The step is already theirs and this question "
    "cannot take it back. If they seem tired, hurried or unsure, leave it out and move on as "
    "usual."
)

# What this turn is, when the pupil has just written their one try at it.
ANSWERING = (
    "Your last question was a harder one of your own, beyond this step's finish line, which "
    "they have already met. They get one try and it changes no mark. Judge what they just "
    "wrote against your own question and put that in assessment, quoting their words. Say what "
    "was right in it, then give what a full answer would have had: it is your question, not "
    "the step's, so explaining it is allowed. Do not ask it again. The platform moves them on "
    "with this reply whatever you judged, so end by asking the next step's first question in "
    'full and put that in task, with move "advance". If they would rather not try it, or ask '
    "what you mean, say that is fine, give the idea in a sentence, and move on the same way."
)

# Added to the help-button line while one is open.
ON_HELP = (
    " It is about your harder question, which is still open: help them with that one, and "
    "leave it open for their try."
)

# Under what is allowed right now, while one is open.
WHILE_OPEN = (
    "Your harder question is the one on screen. The limits above are for the step's own "
    "question, which they have already met; on your own question you may explain in full."
)

_HELPED = ("attempts", "hints", "examples", "worked", "returns", "skipped")

_WENT = {
    Judgment.MET.value: "right",
    Judgment.PARTIAL.value: "partly right",
    Judgment.NOT_MET.value: "not right",
    Judgment.UNCLEAR.value: "not clear",
}


def prose() -> str:
    """Every word the tutor can be told about it, for the scaffold's version."""
    return "\n".join([OFFER, ANSWERING, ON_HELP, WHILE_OPEN])


def offered(
    row: dict,
    *,
    on: bool,
    answering: bool,
    wrong: int,
    left: list[int],
    in_study: bool = False,
    finished: bool = False,
) -> bool:
    """Whether the tutor may ask one on this turn: the teacher switched it on, the pupil has
    just typed their first answer to the step with no wrong try and no help before it, there is
    a step still to do after this one, and the lesson is not in a study arm or finished."""
    if not (on and answering and left) or wrong or in_study or finished:
        return False
    if any(row.get(mark) for mark in _HELPED) or "harder" in row:
        return False
    return row.get("judgment") != Judgment.MET.value


def is_open(row: dict) -> bool:
    """The tutor asked one on this step and the pupil has not answered or left it."""
    return bool((row.get("harder") or {}).get("open"))


def question(row: dict) -> str | None:
    return (row.get("harder") or {}).get("question")


def ask(row: dict, asked: str) -> dict:
    """The step's row with the tutor's harder question open on it."""
    return {**row, "harder": {"question": asked, "open": True}}


def close(row: dict, judgment: str | None = None) -> dict:
    """The row with its open question closed: with the judgment of the pupil's one try, or
    with none when they left it unanswered. A row with none open comes back as it was."""
    if not is_open(row):
        return row
    return {**row, "harder": {"question": question(row), "open": False, "judgment": judgment}}


def went(judgment: str | None) -> str:
    """How the try went, in the words a teacher and the next lesson's tutor read."""
    return _WENT.get(judgment, "not answered")
