"""the learner note as rows: one row for each line, with what it is about and its numbers

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-16

A note kept its lines as sentences inside three lists, so a person looking at the table could
not see what was remembered about a student without opening them. Each line of each version is
now also a row: what it is about, who made it, the numbers it was counted from, and the
sentence a lesson is told. The lists stay, and hold the same sentences.

The notes already written get their rows here, with the numbers read back out of their
sentences. A sentence that is not in a form the server writes today still gets a row, with no
numbers. The view memory_now is each student's latest note, a line to a row.
"""

import re
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEEDS_HELP = re.compile(
    r"(?:Usually needs|Needed) help (once|twice|\d+ times) before getting a step right, "
    r"on (the first try|try \d+) \(from (\d+) steps?\)\."
)
NO_HELP = re.compile(
    r"(?:Usually gets|Got) a step right on (the first try|try \d+), without help "
    r"\(from (\d+) steps?\)\."
)
NONE_RIGHT = re.compile(r"Has not got a step right yet \((\d+) steps? tried\)\.")
FINISHED = re.compile(r"Finished (\d+) of their (\d+) lessons\.")
ONE_LESSON = re.compile(r"(Finished|Did not finish) their one lesson so far\.")
KNOWS = re.compile(
    r"(?P<topics>.+?): (?:(?P<right>\d+) of (?P<counted>\d+) steps? right)?"
    r"(?:\. )?(?:Still mixed up: (?P<mixed_up>.+?))?\.?",
    re.DOTALL,
)

MEMORY_NOW = """
create view memory_now as
select
    student.pseudonym as student,
    note.version as note_version,
    note.created_at as note_written,
    line.position as line,
    line.category,
    line.source,
    line.subject,
    line.topics,
    line.tries,
    line.help,
    line.steps_right,
    line.steps_counted,
    line.lessons_finished,
    line.lessons_counted,
    line.mixed_up,
    line.sentence
from learner_note_lines line
join learner_notes note on note.id = line.note_id
join users student on student.id = note.student_id
where note.version = (
    select max(latest.version) from learner_notes latest
    where latest.student_id = note.student_id
)
order by student.pseudonym, line.position
"""


def _times(said: str) -> int:
    """The number in "once", "twice", "3 times", "the first try" or "try 2"."""
    return {"once": 1, "twice": 2, "the first try": 1}.get(said) or int(
        re.search(r"\d+", said).group()
    )


def _learns(sentence: str) -> dict:
    """A counted line on how a student learns, with the numbers its sentence gives."""
    if found := NEEDS_HELP.fullmatch(sentence):
        helped, on, steps = found.groups()
        return _needs(tries=_times(on), help=_times(helped), right=int(steps), of=int(steps))
    if found := NO_HELP.fullmatch(sentence):
        on, steps = found.groups()
        return _needs(tries=_times(on), help=0, right=int(steps), of=int(steps))
    if found := NONE_RIGHT.fullmatch(sentence):
        return _needs(tries=None, help=None, right=0, of=int(found.group(1)))
    if found := FINISHED.fullmatch(sentence):
        return _finishes(int(found.group(1)), int(found.group(2)))
    if found := ONE_LESSON.fullmatch(sentence):
        return _finishes(int(found.group(1) == "Finished"), 1)
    if sentence.startswith(("Finished", "Did not finish")):
        return {"category": "task_completion"}
    return {"category": "need_for_assistance"}


def _needs(*, tries: int | None, help: int | None, right: int, of: int) -> dict:
    return {
        "category": "need_for_assistance",
        "tries": tries,
        "help": help,
        "steps_right": right,
        "steps_counted": of,
    }


def _finishes(finished: int, of: int) -> dict:
    return {"category": "task_completion", "lessons_finished": finished, "lessons_counted": of}


def _knows(subject: str, sentence: str) -> dict:
    """A counted line on what a student knows. What is still mixed up is as much of it as the
    sentence kept: a sentence cut short ends in "…"."""
    line = {"category": "topic_knowledge", "subject": subject}
    found = KNOWS.fullmatch(sentence)
    if not found or (found["right"] is None and found["mixed_up"] is None):
        return line
    return line | {
        "topics": found["topics"],
        "steps_right": int(found["right"]) if found["right"] else None,
        "steps_counted": int(found["counted"]) if found["counted"] else None,
        "mixed_up": found["mixed_up"],
    }


def _rows(note: sa.Row) -> list[dict]:
    """A note's lines in the order a lesson reads them: how they learn, counted and then
    written, and what they know a subject at a time."""
    lines = [{"source": "counted", "sentence": said} | _learns(said) for said in note.worked_out]
    lines += [
        {"source": "review", "category": "review_note", "sentence": said} for said in note.written
    ]
    lines += [
        {"source": "counted", "sentence": said} | _knows(known.get("subject"), said)
        for known in note.knows
        for said in known.get("lines", [])
    ]
    return [
        {"id": uuid.uuid4(), "note_id": note.id, "position": at, "created_at": note.created_at}
        | line
        for at, line in enumerate(lines, start=1)
    ]


def upgrade() -> None:
    lines = op.create_table(
        "learner_note_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("note_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=True),
        sa.Column("topics", sa.Text(), nullable=True),
        sa.Column("tries", sa.Integer(), nullable=True),
        sa.Column("help", sa.Integer(), nullable=True),
        sa.Column("steps_right", sa.Integer(), nullable=True),
        sa.Column("steps_counted", sa.Integer(), nullable=True),
        sa.Column("lessons_finished", sa.Integer(), nullable=True),
        sa.Column("lessons_counted", sa.Integer(), nullable=True),
        sa.Column("mixed_up", sa.Text(), nullable=True),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category in ('need_for_assistance', 'task_completion', 'topic_knowledge', "
            "'review_note')",
            name="ck_learner_note_line_category",
        ),
        sa.CheckConstraint("source in ('counted', 'review')", name="ck_learner_note_line_source"),
        sa.ForeignKeyConstraint(["note_id"], ["learner_notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "position", name="uq_learner_note_line_position"),
    )

    notes = op.get_bind().execute(
        sa.text("select id, worked_out, written, knows, created_at from learner_notes")
    )
    rows = [row for note in notes for row in _rows(note)]
    if rows:
        # Every row names the same columns, so they go in as one insert.
        empty = dict.fromkeys(column.name for column in lines.columns)
        op.bulk_insert(lines, [empty | row for row in rows])

    op.execute(MEMORY_NOW)


def downgrade() -> None:
    op.execute("drop view memory_now")
    op.drop_table("learner_note_lines")
