"""What the summary and the teacher's screens read back from the record: every step's judgment
reaches the end-of-lesson summary, and a misconception the pupil has since put right is not
shown as one they still hold."""

from app.agent import classroom, memory
from app.enums import EvidenceKind
from app.ledger import append


def turn(message, move="ask", **extra):
    return {"message": message, "move": move, **extra}


OPEN = turn("Hi! Solve 3x + 4 = 19.", task="Solve 3x + 4 = 19")
MIXED_UP = "Adds 4 to both sides instead of taking it away"


def wrong(said, misconception=None):
    return turn(
        "Not yet: what do you do with the 4?",
        move="hint",
        student_attempted=True,
        disclosure="hint",
        assessment={"judgment": "not_met", "evidence_quote": said, "misconception": misconception},
    )


def met(said, task="Next question"):
    return turn(
        "Yes, that's it.",
        move="advance",
        student_attempted=True,
        step_done=True,
        task=task,
        assessment={"judgment": "met", "evidence_quote": said},
    )


async def write(client, c, text):
    r = await client.post(
        f"/api/learn/{c.session.id}/messages", json={"text": text}, headers=c.headers(c.alice)
    )
    assert r.status_code == 200, r.text
    return r.json()


async def lesson(client, c, *pairs):
    """Opens the lesson for Alice and plays (what she writes, the tutor's reply) in order."""
    c.tutor._replies.extend([OPEN, *(reply for _, reply in pairs)])
    r = await client.post(f"/api/learn/{c.session.id}/start", headers=c.headers(c.alice))
    assert r.status_code == 200, r.text
    for said, _ in pairs:
        await write(client, c, said)


def judgments_of(data, pseudonym):
    return next(s for s in data["students"] if s["pseudonym"] == pseudonym)["judgments"]


# ---------- every step reaches the summary ----------


async def summary_view(db, c):
    """The class as the end-of-lesson summary is shown it."""
    data, _ = await classroom.snapshot(db, c.session, per_step=classroom.SUMMARY_PER_STEP)
    return data


async def test_the_summary_is_shown_the_first_step_of_a_finished_pupil(db, client, three):
    """Seen live, twice: a pupil who finished had more than four judgments, the summary was
    handed only the last four, and step 1's quote never reached it."""
    await lesson(
        client,
        three,
        ("x is 7", wrong("x is 7")),
        ("x is 8", wrong("x is 8")),
        ("3x = 15 so x = 5", met("3x = 15 so x = 5")),
        ("x = 4", wrong("x = 4")),
        ("x = 5, 3x = 15", met("x = 5, 3x = 15")),
        ("x = 11", wrong("x = 11")),
        ("x = 12", met("x = 12")),
    )
    judged = judgments_of(await summary_view(db, three), three.alice.pseudonym)
    assert {"step": "Warm up", "judgment": "met", "quote": "3x = 15 so x = 5"}.items() <= next(
        j for j in judged if j["quote"] == "3x = 15 so x = 5"
    ).items()
    # In the order the lesson runs, each step's own judgments together.
    assert [j["step"] for j in judged] == ["Warm up"] * 3 + ["Both sides"] * 2 + ["Brackets"] * 2

    # The teacher's chat, read on every message, is shown each step's latest judgment.
    chat, _ = await classroom.snapshot(db, three.session)
    assert [j["quote"] for j in judgments_of(chat, three.alice.pseudonym)] == [
        "3x = 15 so x = 5",
        "x = 5, 3x = 15",
        "x = 12",
    ]


async def test_the_summary_keeps_each_steps_last_three_judgments(db, client, three):
    await lesson(
        client,
        three,
        *[(f"x is {n}", wrong(f"x is {n}")) for n in (6, 7, 8, 9)],
        ("3x = 15 so x = 5", met("3x = 15 so x = 5")),
    )
    quotes = [
        j["quote"] for j in judgments_of(await summary_view(db, three), three.alice.pseudonym)
    ]
    assert quotes == ["x is 8", "x is 9", "3x = 15 so x = 5"]


async def test_a_busy_class_does_not_push_one_pupils_work_out_of_the_summary(db, client, three):
    """The record was read with a cap of 120 judgments for the whole class: a class of thirty
    reaches that well before the end, and the earliest work fell out."""
    await lesson(client, three, ("3x = 15 so x = 5", met("3x = 15 so x = 5")))
    for n in range(130):
        await append(
            db,
            session_id=three.session.id,
            student_id=three.bob.id,
            kind=EvidenceKind.ASSESSMENT,
            payload={"step_index": n % 3, "step_name": f"Step {n % 3 + 1}", "judgment": "not_met"},
        )
    await db.commit()
    judged = judgments_of(await summary_view(db, three), three.alice.pseudonym)
    assert [j["quote"] for j in judged] == ["3x = 15 so x = 5"]


# ---------- a misconception put right ----------


async def shown_misconceptions(db, c):
    view = await classroom.student_view(db, c.session, c.alice)
    pulse = await classroom.pulse(db, c.session)
    return {
        "card": [line for line in view["summary"] if line.startswith("Misconception seen")],
        "board": [p.note for p in pulse.patterns],
        "across lessons": [
            m
            for t in await memory.knowledge(db, student_id=c.alice.id)
            for m in t["misconceptions"]
        ],
    }


async def test_a_misconception_the_pupil_put_right_is_not_shown_as_held(db, client, three):
    """Seen live: "cats are fluffy" was put right in the next turn, yet the card, the board
    and "across their lessons" kept it as a misconception the pupil holds."""
    await lesson(
        client,
        three,
        ("x = 23 / 3", wrong("x = 23 / 3", misconception=MIXED_UP)),
        ("3x = 15 so x = 5", met("3x = 15 so x = 5")),
    )
    assert await shown_misconceptions(db, three) == {
        "card": [],
        "board": [],
        "across lessons": [],
    }


async def test_a_misconception_not_yet_put_right_is_still_shown(db, client, three):
    await lesson(
        client,
        three,
        ("x = 23 / 3", wrong("x = 23 / 3", misconception=MIXED_UP)),
        ("x is 8", wrong("x is 8")),
    )
    shown = await shown_misconceptions(db, three)
    assert shown["card"] == [f"Misconception seen: {MIXED_UP}."]
    assert shown["board"] == [MIXED_UP]
    assert shown["across lessons"] == [MIXED_UP]


async def test_putting_one_step_right_does_not_clear_another_steps_misconception(db, client, three):
    await lesson(
        client,
        three,
        ("x = 23 / 3", wrong("x = 23 / 3", misconception=MIXED_UP)),
    )
    # A right answer on step 2 says nothing about what was mixed up on step 1.
    await append(
        db,
        session_id=three.session.id,
        student_id=three.alice.id,
        kind=EvidenceKind.ASSESSMENT,
        payload={"step_index": 1, "step_name": "Both sides", "judgment": "met", "topics": []},
    )
    await db.commit()
    assert (await shown_misconceptions(db, three))["card"] == [f"Misconception seen: {MIXED_UP}."]
