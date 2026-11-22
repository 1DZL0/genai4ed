"""The tutor A/B harness: situations seeded as the app keeps them, every scripted message driven
through the real tutor, and a judge that cannot tell which prompt wrote what it reads. A
scripted client stands in for both models, so nothing here calls one."""

import pytest
from sqlalchemy import select

from app.agent import learner
from app.agent.llm import ScriptedClient
from app.agent.student_mode import StudentAgent
from app.models import LessonContract
from bench import tutor_ab
from bench.tutor_ab_cases import SITUATIONS

BY_ID = {s.id: s for s in SITUATIONS}


def _reply(text: str) -> dict:
    return {"message": text, "move": "ask"}


def test_there_is_a_situation_for_every_change():
    assert [s.id for s in SITUATIONS] == [
        "1-misconception",
        "2-reasoning-slip",
        "3-clumsy-english",
        "4-after-hints",
        "5-struggling",
        "6-switched-off",
        "7-second-language",
        "8-overload",
        "9-raise-thinking",
    ]
    assert set().union(*(s.targets for s in SITUATIONS)) == {f"T{n}" for n in range(1, 8)}
    assert all(s.student and s.criteria for s in SITUATIONS)
    # The diagnosis is recorded, not said: the student is never labelled.
    assert any("label" in c for c in BY_ID["1-misconception"].criteria)


async def test_a_situation_is_seeded_with_its_rules_memory_and_adapting(db):
    seeded = await tutor_ab.seed(db, BY_ID["5-struggling"])
    contract = await db.scalar(
        select(LessonContract).where(LessonContract.id == seeded.contract.id)
    )
    assert contract.brief["rules"]["adapt_to_student"] is True
    note = await learner.latest(db, seeded.student.id)
    learns, _ = learner.for_lesson(note, contract.subject)
    assert any("needs help twice" in line for line in learns)


async def test_a_run_drives_every_scripted_message_and_keeps_each_reply(db):
    s = BY_ID["2-reasoning-slip"]
    tutor = ScriptedClient([_reply(f"reply {n}") for n in range(len(s.student) + 1)])
    run = await tutor_ab.run_one(db, s, StudentAgent(tutor))
    assert run.error is None
    # The tutor's opening, then each student line with the tutor's answer to it.
    assert len(run.transcript) == 1 + 2 * len(s.student)
    assert [line["who"] for line in run.transcript[:3]] == ["tutor", "student", "tutor"]
    assert len(run.fields) == 1 + len(s.student)
    assert run.prompt_version.startswith("student-v")


async def test_a_failed_tutor_call_is_recorded_and_does_not_stop_the_set(db):
    s = BY_ID["6-switched-off"]
    run = await tutor_ab.run_one(db, s, StudentAgent(ScriptedClient([_reply("hello")])))
    assert run.error
    assert run.transcript[0]["who"] == "tutor"


def test_the_judge_reads_no_version():
    s = BY_ID["1-misconception"]
    run = tutor_ab.Run(
        transcript=[{"who": "tutor", "text": "Hi"}, {"who": "student", "text": "2/7"}],
        fields=[{"error_kind": "knowledge", "pitch_call": "as_written"}],
        error=None,
        prompt_version="student-v22-abc",
    )
    shown = tutor_ab.judge_input(s, run)
    for word in ("student-v", "error_kind", "pitch"):
        assert word not in shown
    assert "2/7" in shown


async def test_an_unusable_verdict_is_no_verdict():
    s = BY_ID["8-overload"]
    run = tutor_ab.Run(
        transcript=[{"who": "tutor", "text": "Hi"}],
        fields=[],
        error=None,
        prompt_version="student-v1",
    )
    judge = ScriptedClient([{"reason": "no verdict given"}] * 2 * len(s.criteria))
    verdicts = await tutor_ab.judge(judge, s, run)
    assert [v.passed for v in verdicts] == [None] * len(s.criteria)
    row = {"situation": s.id, "verdicts": [v.__dict__ for v in verdicts], "error": None}
    table = tutor_ab.report([row], [row])
    assert "no verdict" in table
    assert "0/1" in table


def test_the_harness_refuses_any_other_database():
    for name in ("genai4ed", "genai4ed_memory", "genai4ed_test"):
        with pytest.raises(SystemExit):
            tutor_ab.guarded_url(f"postgresql+asyncpg://u:p@127.0.0.1:5433/{name}")
    assert tutor_ab.guarded_url("postgresql+asyncpg://u:p@127.0.0.1:5433/genai4ed_ab").endswith(
        "/genai4ed_ab"
    )
