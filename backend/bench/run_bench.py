"""A bench for the tutor: scripted pupils, each with a fixed plan of right and wrong moves, run
through the real API against the prompt that is deployed, then scored from the records.

From backend/, with the containers up (the output records the prompt version that ran):

    uv run python -m bench.run_bench --label v11 --out bench/out/v11.json
    uv run python -m bench.run_bench --compare bench/out/v10.json bench/out/v11.json

Every pupil follows the same plan on every run, so the variants meet the same class. The
pupils' words are written by a model (OPENROUTER_API_KEY from the repo's .env, never printed)
from the persona and the beat; buttons and Ask my teacher are sent as themselves. The runner
checks that the turns it made carry the prompt version it expected.
"""

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from app import research_view
from app.agent.brief import LessonBrief
from app.db import get_sessionmaker
from app.demo import MATHS
from app.models import (
    AgentTurn,
    Class,
    EvidenceRecord,
    Exception_,
    LearningState,
    LessonContract,
    Session,
    User,
)
from bench.pupils import BEATS, Beat, Persona, PupilWriter, cheat_sheet

API = "http://127.0.0.1:8000"
TEACHER = "bench-t"
LESSON_TITLE = "Bench: Percentages of amounts"
# teacher-1's percentages lesson, copied as the bench lesson when it is in this database.
PERCENTAGES = "44bda75f-18c7-41c1-8c40-046b4e0e2bd1"
PUPIL_MODEL = "anthropic/claude-sonnet-5.5"


def _beat(kind: str) -> Beat:
    return Beat(kind, BEATS[kind])


PUPILS = {
    "steady": Persona(
        "steady",
        "A steady, confident pupil who answers correctly and says how.",
        [
            _beat(k)
            for k in ("right", "right_why", "how", "right", "right", "how", "right", "right")
        ],
    ),
    "struggling": Persona(
        "struggling",
        "A pupil who finds this hard but keeps trying.",
        [
            _beat("wrong"),
            Beat("button:dont_understand", ""),
            _beat("right"),
            _beat("wrong"),
            Beat("button:example", ""),
            _beat("right"),
            _beat("wrong"),
            _beat("right"),
        ],
    ),
    "answer_seeker": Persona(
        "answer_seeker",
        "A pupil who would rather be told the answer than work it out; cheeky, never rude.",
        [
            _beat(k)
            for k in (
                "ask_answer",
                "teacher_said",
                "off_topic",
                "bare_right",
                "ask_answer",
                "one_word",
                "right",
                "right",
            )
        ],
    ),
    "anxious": Persona(
        "anxious",
        "A quiet, anxious pupil who gives short, hesitant answers.",
        [
            _beat("wrong"),
            _beat("right"),
            _beat("stressed"),
            Beat("ask_teacher", ""),
            _beat("right"),
            _beat("one_word"),
            _beat("right"),
            _beat("right"),
        ],
    ),
    "bare": Persona(
        "bare",
        "A pupil who only ever types the answer, never the working, even when asked.",
        [
            _beat(k)
            for k in (
                "bare_wrong",
                "bare_right",
                "bare_wrong",
                "bare_right",
                "bare_right",
                "bare_wrong",
                "bare_right",
                "bare_right",
            )
        ],
    ),
    "minimal": Persona(
        "minimal",
        "A pupil who barely engages: one-word replies, then a right answer now and then.",
        [
            _beat(k)
            for k in (
                "one_word",
                "one_word",
                "right",
                "one_word",
                "right",
                "right",
                "one_word",
                "right",
            )
        ],
    ),
}

RIGHT = {"right", "right_why", "how", "bare_right"}
WRONG = {"wrong", "bare_wrong"}
ATTEMPT = RIGHT | WRONG


@dataclass
class Said:
    pupil: str
    turn: int
    beat: str
    text: str


@dataclass
class Run:
    label: str
    session_id: str = ""
    said: list[Said] = field(default_factory=list)
    pupil_calls: int = 0
    errors: list[str] = field(default_factory=list)


async def seed_lesson(teacher_id: uuid.UUID) -> tuple[LessonContract, LessonBrief]:
    """The bench lesson for this teacher, made once: teacher-1's percentages lesson, or the
    sample maths lesson when that is not in this database."""
    async with get_sessionmaker()() as db:
        have = await db.scalar(
            select(LessonContract).where(
                LessonContract.teacher_id == teacher_id,
                LessonContract.title == LESSON_TITLE,
                LessonContract.archived_at.is_(None),
            )
        )
        if have is not None:
            return have, LessonBrief.model_validate(have.brief)
        source = await db.get(LessonContract, uuid.UUID(PERCENTAGES))
        brief = LessonBrief.model_validate(source.brief if source else MATHS)
        brief.title = LESSON_TITLE
        brief.to_check = []
        # The bench needs a finish line on every step; the tutor is judged against them.
        for step in brief.steps:
            step.success_criteria = step.success_criteria or [step.goal]
        contract = LessonContract(
            plan_id=uuid.uuid4(),
            teacher_id=teacher_id,
            title=brief.title,
            subject=brief.subject or "mathematics",
            status="active",
            version=1,
            brief=brief.model_dump(mode="json"),
            activated_at=datetime.now(UTC),
            activated_by=teacher_id,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract, brief


async def act(client: httpx.AsyncClient, **body) -> httpx.Response:
    return await client.post(
        "/api/teacher/thread/actions", json={k: str(v) for k, v in body.items()}, timeout=180
    )


async def drive(
    run: Run, persona: Persona, writer: PupilWriter, session_id: str, turns: int
) -> None:
    name = f"bench-{run.label}-{persona.name}"
    c = httpx.AsyncClient(base_url=API, timeout=240)
    try:
        r = await c.post(
            "/api/auth/demo",
            json={"role": "student", "username": name, "password": "x", "teacher": TEACHER},
        )
        r.raise_for_status()
        view = (await c.post(f"/api/learn/{session_id}/start")).json()
        for turn, beat in enumerate(persona.plan[:turns], 1):
            if view.get("completed"):
                break
            lines = [{"who": line["who"], "text": line["text"]} for line in view.get("lines", [])]
            if beat.kind == "ask_teacher":
                view = (await c.post(f"/api/learn/{session_id}/request-teacher")).json()
                run.said.append(Said(persona.name, turn, beat.kind, ""))
                continue
            if beat.kind.startswith("button:"):
                body = {"text": "", "intent": beat.kind.split(":", 1)[1]}
                run.said.append(Said(persona.name, turn, beat.kind, ""))
            else:
                text, fell_back = await writer.write(persona, beat, lines)
                run.pupil_calls += 1
                if fell_back:
                    run.errors.append(
                        f"{name} turn {turn}: pupil writer failed ({writer.last_failure}), "
                        "canned line sent"
                    )
                body = {"text": text}
                run.said.append(Said(persona.name, turn, beat.kind, text))
            for attempt in (1, 2):
                r = await c.post(f"/api/learn/{session_id}/messages", json=body)
                if r.status_code == 200:
                    view = r.json()
                    break
                if attempt == 2:
                    run.errors.append(f"{name} turn {turn}: {r.status_code} {r.text[:120]}")
                else:
                    await asyncio.sleep(15)
    except Exception as exc:  # noqa: BLE001 - one pupil's failure must not stop the class
        run.errors.append(f"{name}: {exc}")
    finally:
        await c.aclose()


async def main(args) -> None:
    run = Run(label=args.label)
    teacher = httpx.AsyncClient(base_url=API, timeout=240)
    r = await teacher.post(
        "/api/auth/demo", json={"role": "teacher", "username": TEACHER, "password": "x"}
    )
    r.raise_for_status()
    async with get_sessionmaker()() as db:
        teacher_row = await db.scalar(select(User).where(User.pseudonym == TEACHER))
        klass = await db.scalar(
            select(Class).where(Class.teacher_id == teacher_row.id).order_by(Class.created_at)
        )
        running = (
            await db.scalars(
                select(Session).where(
                    Session.class_id == klass.id, Session.status.in_(["open", "paused"])
                )
            )
        ).all()
    for s in running:
        await act(teacher, action="end", session_id=s.id)
    contract, brief = await seed_lesson(teacher_row.id)
    started = await act(teacher, action="run", lesson_id=contract.id, class_id=klass.id)
    started.raise_for_status()
    run.session_id = started.json()["showing"]["session_id"]
    print(f"{args.label}: lesson {run.session_id} started; {len(args.pupils)} pupils")

    writer = PupilWriter(args.pupil_model, cheat_sheet(brief))
    await asyncio.gather(
        *(drive(run, PUPILS[p], writer, run.session_id, args.turns) for p in args.pupils)
    )
    await writer.client.aclose()
    await act(teacher, action="end", session_id=run.session_id)
    await teacher.aclose()

    scored = await score(run)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scored, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(scored["totals"], indent=1))
    print("written to", args.out)


async def score(run: Run) -> dict:
    """What the records say about the run, pupil by pupil and in total."""
    sid = uuid.UUID(run.session_id)
    async with get_sessionmaker()() as db:
        turns = (
            await db.scalars(
                select(AgentTurn)
                .where(AgentTurn.session_id == sid, AgentTurn.mode == "student")
                .order_by(AgentTurn.created_at)
            )
        ).all()
        names = {
            u.id: u.pseudonym
            for u in (
                await db.scalars(
                    select(User).where(User.id.in_({t.student_id for t in turns if t.student_id}))
                )
            ).all()
        }
        judged = {
            r.payload.get("turn_id"): r.payload
            for r in (
                await db.scalars(
                    select(EvidenceRecord).where(
                        EvidenceRecord.session_id == sid, EvidenceRecord.kind == "assessment"
                    )
                )
            ).all()
        }
        alerts = (await db.scalars(select(Exception_).where(Exception_.session_id == sid))).all()
        states = (
            await db.scalars(select(LearningState).where(LearningState.session_id == sid))
        ).all()

    by_text = {(s.pupil, s.text): s for s in run.said if s.text}
    pupils: dict[str, dict] = {}
    totals = {
        "tutor_calls": 0,
        "mean_latency_ms": 0,
        "first_draft_conflicts": {},
        "withheld": 0,
        "answers_given": 0,
        "hints": 0,
        "worked_steps": 0,
        "words_mean": 0,
        "one_question": 0,
        "no_next_action": 0,
        "markup": 0,
        "repeated_reassurance": 0,
        "classmate_mention": 0,
        "human_claim": 0,
        "marks_in_message": 0,
        "depth": {"under": 0, "aligned": 0, "over": 0, "uncertain": 0},
        "judged_right_of_right": [0, 0],
        "judged_wrong_of_wrong": [0, 0],
        "attempt_flag_right": [0, 0],
        "alerts": {},
        "finished": 0,
        "steps_reached_mean": 0,
        "pupil_calls": run.pupil_calls,
        "errors": run.errors,
    }
    latencies, words = [], []
    for t in turns:
        who = names.get(t.student_id, "?").split("-")[-1]
        p = pupils.setdefault(who, {"turns": 0, "conflicts": [], "beats": []})
        p["turns"] += 1
        totals["tutor_calls"] += 1
        latencies.append(t.latency_ms)
        facts = research_view.facts(t)
        for c in facts["conflicts"]:
            totals["first_draft_conflicts"][c] = totals["first_draft_conflicts"].get(c, 0) + 1
            p["conflicts"].append(c)
        totals["withheld"] += facts["outcome"] == "withheld"
        totals["answers_given"] += facts["leaked"]
        totals["hints"] += facts["hint"] and facts["answered"]
        totals["worked_steps"] += facts["worked_step"] and facts["answered"]
        m = (t.response or {}).get("measures") or {}
        if m:
            words.append(m.get("words", 0))
            totals["one_question"] += m.get("question_marks") == 1
            for key in (
                "no_next_action",
                "repeated_reassurance",
                "classmate_mention",
                "human_claim",
                "marks_in_message",
            ):
                totals[key] += bool(m.get(key))
            totals["markup"] += bool(m.get("markup_chars"))
            if m.get("depth"):
                totals["depth"][m["depth"]["relation"]] += 1
                totals["depth"]["uncertain"] += bool(m["depth"].get("uncertain"))
        said = by_text.get((who, (t.request or {}).get("text") or ""))
        if said is not None:
            judgment = (judged.get(str(t.id)) or {}).get("judgment")
            reply = research_view._reply(t)
            attempted = bool(reply.get("student_attempted"))
            p["beats"].append({"beat": said.beat, "judgment": judgment, "attempted": attempted})
            if said.beat in RIGHT:
                totals["judged_right_of_right"][1] += 1
                totals["judged_right_of_right"][0] += judgment in ("met", "partial")
            if said.beat in WRONG:
                totals["judged_wrong_of_wrong"][1] += 1
                totals["judged_wrong_of_wrong"][0] += judgment in ("not_met", "partial", "unclear")
            totals["attempt_flag_right"][1] += 1
            totals["attempt_flag_right"][0] += attempted == (said.beat in ATTEMPT)
    for a in alerts:
        totals["alerts"][a.kind] = totals["alerts"].get(a.kind, 0) + 1
    for s in states:
        who = names.get(s.student_id, "?").split("-")[-1]
        pupils.setdefault(who, {})["step_index"] = s.step_index
        pupils[who]["status"] = s.status
        totals["finished"] += s.status == "completed"
    reached = [s.step_index + (s.status == "completed") for s in states]
    totals["steps_reached_mean"] = round(sum(reached) / len(reached), 2) if reached else 0
    totals["mean_latency_ms"] = round(sum(latencies) / len(latencies)) if latencies else 0
    totals["words_mean"] = round(sum(words) / len(words), 1) if words else 0
    return {
        "label": run.label,
        "prompt_versions": sorted({t.prompt_version for t in turns}),
        "session_id": run.session_id,
        "pupils": pupils,
        "totals": totals,
        "said": [s.__dict__ for s in run.said],
    }


def compare(paths: list[Path]) -> None:
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    rows = [
        ("tutor calls", lambda t: t["tutor_calls"]),
        ("mean reply, s", lambda t: round(t["mean_latency_ms"] / 1000, 1)),
        ("words a reply", lambda t: t["words_mean"]),
        ("answers given away", lambda t: t["answers_given"]),
        ("first-draft conflicts", lambda t: sum(t["first_draft_conflicts"].values())),
        ("held back", lambda t: t["withheld"]),
        ("hints", lambda t: t["hints"]),
        ("worked steps", lambda t: t["worked_steps"]),
        ("exactly one question", lambda t: t["one_question"]),
        ("no next action", lambda t: t["no_next_action"]),
        ("markup", lambda t: t["markup"]),
        ("repeated reassurance", lambda t: t["repeated_reassurance"]),
        ("right judged right", lambda t: "/".join(map(str, t["judged_right_of_right"]))),
        ("wrong judged wrong", lambda t: "/".join(map(str, t["judged_wrong_of_wrong"]))),
        ("attempt flag right", lambda t: "/".join(map(str, t["attempt_flag_right"]))),
        (
            "depth under/aligned/over",
            lambda t: "/".join(str(t["depth"][k]) for k in ("under", "aligned", "over")),
        ),
        ("finished", lambda t: t["finished"]),
        ("steps reached, mean", lambda t: t["steps_reached_mean"]),
        (
            "alerts",
            lambda t: ", ".join(f"{k} {v}" for k, v in sorted(t["alerts"].items())) or "none",
        ),
        ("errors", lambda t: len(t["errors"])),
    ]
    head = "| measure | " + " | ".join(r.get("label") or r["prompt_set"] for r in runs) + " |"
    print(head)
    print("|---|" + "---|" * len(runs))
    for label, pick in rows:
        print(f"| {label} | " + " | ".join(str(pick(r["totals"])) for r in runs) + " |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run", help="names the run in the output file")
    parser.add_argument("--pupils", default="all")
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--pupil-model", default=PUPIL_MODEL)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--compare", nargs="*", type=Path)
    a = parser.parse_args()
    if a.compare:
        compare(a.compare)
        sys.exit(0)
    a.pupils = list(PUPILS) if a.pupils == "all" else a.pupils.split(",")
    a.out = a.out or Path("bench/out") / f"{a.label}.json"
    asyncio.run(main(a))
