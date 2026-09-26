"""The teacher's one conversation with the class agent. The agent chooses what
to show and the server builds the card from records; anything that changes
state is a button the teacher presses.
"""

import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import classroom, store, supervisor
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, LLMError, ask_structured, image_part
from app.agent.policy import PolicyRules, from_teachers_words
from app.config import get_settings
from app.enums import (
    ConflictCode,
    ContractStatus,
    ConversationKind,
    ExceptionStatus,
    LeakageCheck,
    MessageRole,
    ScoreStatus,
    SessionStatus,
    ValidationOutcome,
)
from app.models import (
    AgentTurn,
    Class,
    ClassInsight,
    Enrolment,
    Exception_,
    LessonContract,
    LessonOutcome,
    Material,
    Message,
    Session,
    User,
)

POLICY_VERSION = "class-agent-v1"
PROMPT_VERSION = "teacher-thread-v1"
WINDOW = 24
MATERIAL_CHARS = 24_000

SYSTEM = """\
You are the class agent. This is your one conversation with a teacher. You help them \
shape a lesson, you teach it to each of their students one to one, and you report back.

Every turn, reply in "reply" like a colleague, not a form: two or three short sentences, \
never a lesson written out in prose - the detail belongs in the brief, which the teacher \
sees beside your reply. Say what you actually did and what you were unsure about, in your \
own words; never reuse the sentence you used last time. Then choose what to put on screen \
with "show":
- "lesson": the lesson brief. Use it whenever you create or change a lesson.
- "lessons": their lessons, when they ask what they have.
- "class": how a class is getting on in a running or finished lesson.
- "student": one student's progress and evidence. Put their pseudonym in "student_ref".
- "outcomes": the suggested outcomes after a lesson.
- "nothing": when a sentence is the whole answer.
Only return a "brief" when the teacher is asking for a lesson to be made or changed. A \
question about what they already have is answered with "lessons" or "lesson" and no brief \
- never redraft a lesson because they asked you about it. When they describe a lesson to \
teach, draft it in that same reply; never ask them to choose between lessons they have.
Name the lesson you mean in "lesson_ref" (its title or id) when it isn't the one in focus.

Making a lesson: the teacher writes it and it stays theirs - their words, their steps, \
their order, their questions. Return the whole brief as it should now be in "brief", and \
set "new_lesson" true if it is a new lesson rather than a change to the one in focus. Fill \
in only what they left out (a title, a step's success criteria, a reference answer, the \
time) and say in your reply what you filled in. Never restructure, reword, add or remove \
steps unless they ask. If they gave only a topic, draft a short skeleton for them to fill \
in and say so. Shape it as:
- Always fill in "title" (a few words a teacher would recognise on a timetable, never \
"New lesson"), "subject", "duration_minutes", and "year_group" and "prior_knowledge" \
where the teacher has said them. A lesson with no title cannot be approved.
- Objectives: what students should understand or be able to do, in plain words.
- Steps: the teacher's steps as they gave them, each with a kind (explain, question, \
practice, check). Each step has a goal, prompt ideas (the actual \
questions, with the actual numbers or texts - never a description of a question), success \
criteria you can judge answers against, and a reference answer only where the step has a \
definite answer (a value, a word, a fact; never a method or an explanation, which cannot \
be kept from a student who is being taught it). Students never see reference answers.
- Strategy: level, order, tone, what to emphasise, how to use prior knowledge.
- Assessment: a few criteria with points, if the work should be judged.
- Topics: 1-4 short lowercase tags.
- Rules: keep the teacher's words in "rules_text" and compile them into "rules": \
hints_allowed; partial_after_attempts (how many tries before a worked step, 1 or more \
unless the teacher says otherwise); full_answer_after_attempts (how many tries before \
the answer itself - null means never, and "never give them the answer", "they must work \
it out" or "no final answers" all mean null, not a number); may_write_for_student; \
ladder (true only when the teacher asks for help in a fixed order, one step at a time); \
escalations [{signal, after, action}] over signals struggling, misconception, \
manipulation_attempt, off_task, fast_progress, unresolved_question, wellbeing, \
asked_for_teacher with actions log, summarise, alert; notes for anything else.
Working it out together: if the teacher hasn't said who the students are and what they \
already know, how long the lesson is, or what they should be able to do by the end, draft \
anyway with your best assumption, say what you assumed, and ask about the one or two that \
matter most - never a questionnaire, and never a question they have already answered. \
When their material suggests something they didn't ask for - an activity built from a \
figure, an example from their notes - propose it in your reply as a question and leave it \
out of the brief until they say yes. When the class data shows several students sharing a \
difficulty, say so with the numbers and offer to draft a short follow-up activity on it.
Compile only what the teacher actually said; don't invent a limit they didn't ask for. \
A new lesson starts with no rules: leave "rules_text" empty and "rules" at their defaults \
unless the teacher stated rules for this lesson - never carry over the rules of the lesson \
in focus or of a sample. \
If a rule is ambiguous, take the stricter reading, and say in your reply what you took \
it to mean so they can correct you.

You cannot approve a lesson, start or end one, pause it, confirm an outcome, change a \
mark or send anything to students: those are buttons the teacher presses, and you have no \
way to press them. Never say you have done one, and never offer to - say which button they \
can press instead. Never promise to report back later: you speak only when written to. \
Use only the data below and ordinary \
subject knowledge suitable for school. Describe students by pseudonym, as observations. \
Say only what the class data shows: a student with no judged work has no misconception, \
and a lesson is finished only when its status says closed. When asked who needs attention, \
name everyone the data flags, and nobody it doesn't.
"""


class TeacherTurnOut(BaseModel):
    reply: str = Field(min_length=1, max_length=2000)
    show: Literal["nothing", "lesson", "lessons", "class", "student", "outcomes"] = "nothing"
    lesson_ref: str | None = Field(default=None, max_length=255)
    student_ref: str | None = Field(default=None, max_length=64)
    brief: LessonBrief | None = None
    new_lesson: bool = False


# A long message about a lesson that is not a question must come back with a brief.
_LESSON_WORDS = re.compile(r"\b(lesson|teach|activity|class|minutes?|year \d+)\b", re.IGNORECASE)


def _describes_a_lesson(text: str) -> bool:
    words = text.split()
    return len(words) >= 12 and not text.rstrip().endswith("?") and bool(_LESSON_WORDS.search(text))


def _must_draft(out: "TeacherTurnOut") -> None:
    if out.brief is None:
        raise ValueError(
            'The teacher described a lesson to teach. Return it in "brief" with show "lesson".'
        )


_ASKS_NEW = re.compile(
    r"\b(?:new|another|separate|second|next) lesson\b|\bfollow[- ]?up\b", re.IGNORECASE
)


def _sentences(text: str) -> list[str]:
    return [line.strip() for line in re.split(r"(?<=[.!?])\s+", text) if line.strip()]


class ThreadUnavailable(Exception):
    """The model couldn't answer. The teacher's message is kept."""


@dataclass
class Focus:
    """What the thread is currently about."""

    lesson: LessonContract | None = None
    session: Session | None = None


def _next_button(focus: Focus) -> str:
    """What the teacher can press next."""
    if focus.session is not None and focus.session.status != SessionStatus.CLOSED.value:
        return "Pause and End the lesson are on the class card."
    if focus.lesson is not None and focus.lesson.status == ContractStatus.DRAFT.value:
        return "Approve it on the lesson card, then choose a class and press Start."
    if focus.lesson is not None:
        return "Choose a class on the lesson card and press Start."
    return ""


# ---------- what the teacher has ----------


async def _lessons(db: AsyncSession, teacher: User) -> list[LessonContract]:
    """The latest version of each of the teacher's lessons, newest first."""
    rows = (
        await db.scalars(
            select(LessonContract)
            .where(LessonContract.teacher_id == teacher.id, LessonContract.archived_at.is_(None))
            .order_by(LessonContract.plan_id, LessonContract.version.desc())
        )
    ).all()
    latest: dict[uuid.UUID, LessonContract] = {}
    for row in rows:
        latest.setdefault(row.plan_id, row)
    return sorted(latest.values(), key=lambda c: c.created_at, reverse=True)


async def _live(db: AsyncSession, teacher: User) -> list[Session]:
    """The teacher's open or paused lessons, newest first."""
    return list(
        (
            await db.scalars(
                select(Session)
                .join(Class, Class.id == Session.class_id)
                .where(
                    Class.teacher_id == teacher.id,
                    Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
                )
                .order_by(Session.created_at.desc())
            )
        ).all()
    )


async def _classes(db: AsyncSession, teacher: User) -> list[tuple[Class, int]]:
    classes = (
        await db.scalars(select(Class).where(Class.teacher_id == teacher.id).order_by(Class.label))
    ).all()
    out = []
    for klass in classes:
        size = await db.scalar(
            select(func.count(Enrolment.id)).where(Enrolment.class_id == klass.id)
        )
        out.append((klass, size or 0))
    return out


async def focus_of(db: AsyncSession, conversation, teacher: User) -> Focus:
    """The lesson or live lesson the last few messages were about."""
    for message in reversed(await store.messages(db, conversation.id, limit=WINDOW)):
        if message.data.get("clears_focus"):
            return Focus()
        card = message.data.get("card") or {}
        lesson_id = card.get("lesson_id") or message.data.get("lesson_id")
        session_id = card.get("session_id") or message.data.get("session_id")
        if session_id:
            session = await db.get(Session, uuid.UUID(str(session_id)))
            if session is not None:
                return Focus(await db.get(LessonContract, session.contract_id), session)
        if lesson_id:
            lesson = await db.get(LessonContract, uuid.UUID(str(lesson_id)))
            if lesson is not None and lesson.teacher_id == teacher.id:
                return Focus(lesson, None)
    live = await _live(db, teacher)
    if live:
        return Focus(await db.get(LessonContract, live[0].contract_id), live[0])
    return Focus()


async def _resolve(db: AsyncSession, teacher: User, ref: str | None, focus: Focus):
    """The lesson the teacher means: an id, a title, or the one in focus."""
    if not ref:
        return focus.lesson
    try:
        found = await db.get(LessonContract, uuid.UUID(ref))
        if found is not None and found.teacher_id == teacher.id:
            return found
    except ValueError:
        pass
    wanted = ref.strip().lower()
    lessons = await _lessons(db, teacher)
    for lesson in lessons:
        if lesson.title.strip().lower() == wanted:
            return lesson
    for lesson in lessons:
        if wanted in lesson.title.strip().lower():
            return lesson
    return focus.lesson


# ---------- what the agent is shown ----------


async def _materials(db: AsyncSession, plan_id: uuid.UUID) -> list[Material]:
    return list(
        (
            await db.scalars(
                select(Material).where(Material.plan_id == plan_id).order_by(Material.created_at)
            )
        ).all()
    )


async def _system(db: AsyncSession, teacher: User, focus: Focus) -> tuple[str, dict]:
    """The prompt and the manifest of what went into it."""
    lessons = await _lessons(db, teacher)
    live = await _live(db, teacher)
    parts = [SYSTEM]
    manifest: dict = {
        "mode": "teacher",
        "lesson_ids": [str(c.id) for c in lessons],
        "session_ids": [str(s.id) for s in live],
    }

    parts.append(
        "\nTheir lessons:\n"
        + json.dumps(
            [
                {
                    "id": str(c.id),
                    "title": c.title,
                    "subject": c.subject,
                    "status": c.status,
                    "steps": len((c.brief or {}).get("steps") or []),
                }
                for c in lessons
            ]
        )
    )
    parts.append(
        "\nTheir classes:\n"
        + json.dumps([{"label": k.label, "students": n} for k, n in await _classes(db, teacher)])
    )

    if focus.lesson is not None:
        brief = LessonBrief.model_validate(focus.lesson.brief or {})
        parts.append(
            f"\nThe lesson in focus is id {focus.lesson.id} ({focus.lesson.status}, "
            f"version {focus.lesson.version}).\nThe lesson in focus:\n" + brief.model_dump_json()
        )
        needed = ", ".join(brief.missing()) or "nothing"
        parts.append(f"\nStill needed before it can be approved: {needed}.")
        materials = await _materials(db, focus.lesson.plan_id)
        manifest["material_ids"] = [str(m.id) for m in materials]
        budget = MATERIAL_CHARS
        excerpts = []
        for m in materials:
            if m.extracted_text and budget > 0:
                excerpt = m.extracted_text[:budget]
                budget -= len(excerpt)
                excerpts.append(f"--- {m.filename} ---\n{excerpt}")
        if excerpts:
            parts.append("\nTheir materials:\n" + "\n\n".join(excerpts))

    if focus.session is not None and focus.session.status != SessionStatus.SCHEDULED.value:
        data, class_manifest = await classroom.snapshot(db, focus.session)
        manifest["class"] = class_manifest
        taught = await db.get(LessonContract, focus.session.contract_id)
        same = (
            focus.lesson is not None
            and taught is not None
            and taught.plan_id == focus.lesson.plan_id
        )
        parts.append(
            f"\nThe class in focus is session id {focus.session.id} ({focus.session.status}), "
            f"being taught “{taught.title if taught else ''}”"
            + (
                ""
                if same
                else " - a different lesson from the one in focus above, which is not running"
            )
            + ".\nThe class right now:\n"
            + json.dumps(data)
        )
    elif live:
        running = ", ".join(str(s.id) for s in live)
        parts.append(f"\nRunning now: {len(live)} lesson(s), ids {running}.")
    return "\n".join(parts), manifest


async def _history(db: AsyncSession, conversation, materials: list[Material]) -> list[dict]:
    """The recent thread as model messages, with attached images inline."""
    images = {str(m.id): m for m in materials if m.media_type.startswith("image/")}
    out: list[dict] = []
    for m in await store.messages(db, conversation.id, limit=WINDOW):
        if m.role == MessageRole.TEACHER.value:
            attached = [images[i] for i in m.material_ids if i in images]
            out.append(
                {
                    "role": "user",
                    "content": (
                        [
                            {"type": "text", "text": m.text},
                            *[image_part(a.media_type, a.content) for a in attached],
                        ]
                        if attached
                        else m.text
                    ),
                }
            )
        elif m.role == MessageRole.AGENT.value:
            out.append({"role": "assistant", "content": m.text})
        elif m.text:  # an event: an approval, a lesson starting
            out.append({"role": "user", "content": f"[{m.text}]"})
    return out


# ---------- the turn ----------


def _turn(conversation_id, manifest, client, result, tries, request, *, session_id=None):
    """The audit row for one call to the model; `result` is None when it failed."""
    if result is None:
        outcome = ValidationOutcome.WITHHELD
    elif tries == 1:
        outcome = ValidationOutcome.OK
    else:
        outcome = ValidationOutcome.REGENERATED
    return AgentTurn(
        session_id=session_id,
        conversation_id=conversation_id,
        mode=ConversationKind.TEACHER.value,
        context_manifest=manifest,
        policy_version=POLICY_VERSION,
        prompt_version=PROMPT_VERSION,
        provider=result.provider if result else client.name,
        model=result.model if result else client.model,
        latency_ms=result.latency_ms if result else 0,
        validation_outcome=outcome.value,
        leakage_check=LeakageCheck.SKIPPED.value,
        conflicts=[] if result else ["malformed_output"],
        request=request,
        response={"raw": result.raw[:12000]} if result else {},
    )


async def draft_to_work_on(db: AsyncSession, contract: LessonContract) -> LessonContract:
    """The draft the teacher's next words change: this one, the plan's open draft,
    or a new draft copied from this version."""
    if contract.status == ContractStatus.DRAFT.value:
        return contract
    versions = (
        await db.scalars(
            select(LessonContract)
            .where(LessonContract.plan_id == contract.plan_id)
            .order_by(LessonContract.version)
        )
    ).all()
    draft = next((v for v in versions if v.status == ContractStatus.DRAFT.value), None)
    if draft is not None:
        return draft
    draft = LessonContract(
        plan_id=contract.plan_id,
        teacher_id=contract.teacher_id,
        title=contract.title,
        subject=contract.subject,
        status=ContractStatus.DRAFT.value,
        version=versions[-1].version + 1,
        brief=dict(contract.brief or {}),
        use_past_lessons=contract.use_past_lessons,
    )
    db.add(draft)
    await db.flush()
    return draft


def new_lesson(db: AsyncSession, teacher: User) -> LessonContract:
    contract = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=teacher.id,
        title="New lesson",
        subject="",
        status=ContractStatus.DRAFT.value,
        version=1,
        brief={},
    )
    db.add(contract)
    return contract


def _same_lesson(base: LessonContract, brief: LessonBrief, *, claimed_new: bool = False) -> bool:
    """Whether `brief` is a version of `base` rather than a different lesson."""
    old = LessonBrief.model_validate(base.brief or {})
    if not old.title.strip() and not old.steps:
        return True  # an empty draft becomes whatever is put in it
    if old.subject.strip().lower() != brief.subject.strip().lower():
        return False
    if old.title.strip().lower() == brief.title.strip().lower():
        return True
    # The model's "new_lesson" only counts when the title changed too.
    return not claimed_new and bool(set(old.topics) & set(brief.topics))


_RULE_WORDS = re.compile(
    r"\b(hint|answer|rule|flag|tell me|never|allow|attempt|tr(y|ies)|write|upset|wellbeing)",
    re.IGNORECASE,
)


async def _drop_carried_rules(db: AsyncSession, teacher: User, out: TeacherTurnOut, said: str):
    """Drop rules copied from another lesson when the teacher said nothing about rules."""
    assert out.brief is not None
    if not out.brief.rules_text.strip() or _RULE_WORDS.search(said):
        return
    mine = supervisor.normalise(out.brief.rules_text)
    for other in await _lessons(db, teacher):
        brief = LessonBrief.model_validate(other.brief or {})
        if mine == supervisor.normalise(brief.rules_text) or out.brief.rules == brief.rules:
            out.brief.rules_text = ""
            out.brief.rules = PolicyRules()
            return


async def _apply_brief(
    db: AsyncSession,
    teacher: User,
    out: TeacherTurnOut,
    focus: Focus,
    *,
    said: str = "",
    force_new: bool = False,
) -> LessonContract | None:
    """Write the brief the model returned into a draft, new or existing."""
    if out.brief is None:
        return None
    base = None if force_new else await _resolve(db, teacher, out.lesson_ref, focus)
    if base is not None:
        # A change that comes back without a title or subject keeps the ones it had.
        old = LessonBrief.model_validate(base.brief or {})
        out.brief.title = out.brief.title.strip() or old.title
        out.brief.subject = out.brief.subject.strip() or old.subject
        if not _same_lesson(base, out.brief, claimed_new=out.new_lesson):
            base = None
    if base is None:
        await _drop_carried_rules(db, teacher, out, said)
    # The teacher's own words outrank the model's reading of them.
    out.brief.rules = from_teachers_words(out.brief.rules, out.brief.rules_text)
    contract = new_lesson(db, teacher) if base is None else await draft_to_work_on(db, base)
    contract.brief = out.brief.model_dump(mode="json")
    if out.brief.title.strip():
        contract.title = out.brief.title.strip()[:255]
    if out.brief.subject.strip():
        contract.subject = out.brief.subject.strip()[:64]
    await db.flush()
    return contract


async def _chosen_card(
    db: AsyncSession,
    teacher: User,
    out: TeacherTurnOut,
    focus: Focus,
    changed: LessonContract | None,
) -> dict | None:
    """The card the agent asked for, as the ids the server builds it from."""
    if out.show == "nothing":
        return None
    if out.show == "lessons":
        return {"type": "lessons"}
    if out.show == "lesson" or changed is not None:
        lesson = changed or await _resolve(db, teacher, out.lesson_ref, focus)
        return {"type": "lesson", "lesson_id": str(lesson.id)} if lesson else {"type": "lessons"}
    session = focus.session
    if session is None:
        session = next(iter(await _live(db, teacher)), None)
    if session is None:
        return None
    if out.show == "outcomes":
        return {"type": "outcomes", "session_id": str(session.id)}
    if out.show == "student" and out.student_ref:
        wanted = out.student_ref.strip().lower()
        for s in (await classroom.pulse(db, session)).students:
            if s.pseudonym.lower() == wanted:
                return {
                    "type": "student",
                    "session_id": str(session.id),
                    "student_id": str(s.student_id),
                }
    return {"type": "class", "session_id": str(session.id)}


async def respond(
    db: AsyncSession,
    client: LLMClient,
    *,
    teacher: User,
    text: str,
    material_ids: list[uuid.UUID] | None = None,
    force_new: bool = False,
) -> Message:
    """One turn: the teacher's message in, the agent's reply and at most one card out.
    `force_new` makes any brief in the reply a new lesson."""
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    await store.add_message(
        db,
        conversation,
        role=MessageRole.TEACHER,
        text=text,
        material_ids=[str(m) for m in material_ids or []],
    )
    focus = await focus_of(db, conversation, teacher)
    system, manifest = await _system(db, teacher, focus)
    materials = await _materials(db, focus.lesson.plan_id) if focus.lesson else []
    history = await _history(db, conversation, materials)
    manifest["message_count"] = len(history)
    request = {"text": text, "material_ids": [str(m) for m in material_ids or []]}

    try:
        out, result, tries = await ask_structured(
            client,
            TeacherTurnOut,
            purpose="teacher_thread",
            system=system,
            messages=history,
            max_tokens=6000,
            check=_must_draft if _describes_a_lesson(text) else None,
        )
    except LLMError as exc:
        db.add(
            _turn(
                conversation.id,
                manifest,
                client,
                None,
                0,
                request | {"error": str(exc)[:500], "raw": getattr(exc, "raw", "")[:4000]},
            )
        )
        await db.commit()
        raise ThreadUnavailable(str(exc)) from exc

    turn = _turn(
        conversation.id,
        manifest,
        client,
        result,
        tries,
        request,
        session_id=focus.session.id if focus.session else None,
    )
    db.add(turn)
    await db.flush()

    conflicts: list[str] = []
    claimed = supervisor.claims_teacher_action(out.reply)
    if claimed:
        out.reply = supervisor.without_claims(out.reply, claimed, _next_button(focus))
        out.show = "class" if focus.session is not None else "lesson"
        conflicts.append(ConflictCode.FALSE_CLAIM.value)

    # Nothing may be said about a student who has not said anything yet.
    if focus.session is not None:
        silent = {
            s.pseudonym for s in (await classroom.pulse(db, focus.session)).students if s.turns == 0
        }
        invented = supervisor.names_without_evidence(out.reply, silent)
        if invented:
            kept = [line for line in _sentences(out.reply) if line not in invented]
            kept.append(
                "I can only go on what students have actually done, and "
                f"{'nobody has' if len(silent) > 1 else 'they have not'} started yet."
            )
            out.reply = " ".join(kept)
            conflicts.append(ConflictCode.FALSE_CLAIM.value)

    if conflicts:
        turn.conflicts = conflicts
        turn.validation_outcome = ValidationOutcome.REGENERATED.value

    force_new = force_new or bool(_ASKS_NEW.search(text))
    changed = await _apply_brief(db, teacher, out, focus, said=text, force_new=force_new)
    card = await _chosen_card(db, teacher, out, focus, changed)
    reply = await store.add_message(
        db,
        conversation,
        role=MessageRole.AGENT,
        text=out.reply,
        data={"card": card} if card else {},
        turn_id=turn.id,
    )
    await db.commit()
    return reply


async def event(
    db: AsyncSession,
    teacher: User,
    *,
    text: str,
    card: dict | None = None,
    lesson_id: str | None = None,
    session_id: str | None = None,
    clears_focus: bool = False,
) -> Message:
    """Something the teacher did, written into the thread. With no text it only
    marks what the next thing said will change."""
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    data = {
        "card": card,
        "lesson_id": lesson_id,
        "session_id": session_id,
        "clears_focus": clears_focus,
    }
    data = {k: v for k, v in data.items() if v}
    return await store.add_message(db, conversation, role=MessageRole.EVENT, text=text, data=data)


# ---------- cards, built from records every time the thread is read ----------


async def _runs(db: AsyncSession, plan_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(Session, Class)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .join(Class, Class.id == Session.class_id)
            .where(LessonContract.plan_id == plan_id)
            .order_by(Session.created_at.desc())
        )
    ).all()
    runs = []
    for session, klass in rows:
        alerts = await db.scalar(
            select(func.count(Exception_.id)).where(
                Exception_.session_id == session.id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
        waiting = await db.scalar(
            select(func.count(LessonOutcome.id)).where(
                LessonOutcome.session_id == session.id,
                LessonOutcome.status == ScoreStatus.SUGGESTED.value,
            )
        )
        runs.append(
            {
                "session_id": str(session.id),
                "class_label": klass.label,
                "status": session.status,
                "opened_at": classroom.when(session.opened_at),
                "closed_at": classroom.when(session.closed_at),
                "open_alerts": alerts or 0,
                "outcomes_to_confirm": waiting or 0,
            }
        )
    return runs


def _live_run(runs: list[dict]) -> dict | None:
    live = (SessionStatus.OPEN.value, SessionStatus.PAUSED.value)
    return next((r for r in runs if r["status"] in live), None)


async def _lesson_card(db: AsyncSession, teacher: User, lesson: LessonContract) -> dict:
    brief = LessonBrief.model_validate(lesson.brief or {})
    approved = await db.scalar(
        select(LessonContract)
        .where(
            LessonContract.plan_id == lesson.plan_id,
            LessonContract.status == ContractStatus.ACTIVE.value,
        )
        .order_by(LessonContract.version.desc())
    )
    runs = await _runs(db, lesson.plan_id)
    return {
        "type": "lesson",
        "lesson_id": str(lesson.id),
        "plan_id": str(lesson.plan_id),
        "version": lesson.version,
        "status": lesson.status,
        "title": brief.title or lesson.title,
        "subject": brief.subject or lesson.subject,
        "duration_minutes": brief.duration_minutes,
        "objectives": brief.objectives,
        "strategy": brief.strategy,
        "steps": [
            {
                "name": s.name,
                "kind": s.kind,
                "goal": s.goal,
                "criteria": s.success_criteria,
                "has_reference": bool(s.reference_answer),
            }
            for s in brief.steps
        ],
        "assessment": [c.model_dump() for c in brief.assessment],
        "rules_text": brief.rules_text,
        "rules_in_words": brief.rules.describe(),
        "missing": brief.missing(),
        "use_past_lessons": lesson.use_past_lessons,
        # In a study the researcher assigns this, so the teacher is not offered it.
        "study": get_settings().study_active,
        "approved_lesson_id": str(approved.id) if approved else None,
        "materials": [
            {
                "id": str(m.id),
                "filename": m.filename,
                "readable": bool(m.extracted_text) or m.media_type.startswith("image/"),
            }
            for m in await _materials(db, lesson.plan_id)
        ],
        "classes": [
            {"id": str(k.id), "label": k.label, "students": n}
            for k, n in await _classes(db, teacher)
        ],
        "live": _live_run(runs),
        "runs": runs,
    }


async def lessons_card(db: AsyncSession, teacher: User) -> dict:
    lessons = []
    for c in await _lessons(db, teacher):
        brief = LessonBrief.model_validate(c.brief or {})
        runs = await _runs(db, c.plan_id)
        closed = [r for r in runs if r["status"] == SessionStatus.CLOSED.value]
        lessons.append(
            {
                "lesson_id": str(c.id),
                "plan_id": str(c.plan_id),
                "title": brief.title or c.title,
                "subject": brief.subject or c.subject,
                "status": c.status,
                "steps": len(brief.steps),
                "duration_minutes": brief.duration_minutes,
                "ready": not brief.missing(),
                "live": _live_run(runs),
                "last_run": closed[0] if closed else None,
            }
        )
    return {
        "type": "lessons",
        "lessons": lessons,
        "classes": [
            {"id": str(k.id), "label": k.label, "students": n}
            for k, n in await _classes(db, teacher)
        ],
    }


async def _class_card(db: AsyncSession, session: Session) -> dict:
    p = await classroom.pulse(db, session)
    klass = await db.get(Class, session.class_id)
    contract = await db.get(LessonContract, session.contract_id)
    return {
        "type": "class",
        "session_id": str(session.id),
        "lesson_id": str(contract.id),
        "title": p.brief.title or contract.title,
        "class_label": klass.label if klass else "",
        "status": session.status,
        "opened_at": classroom.when(session.opened_at),
        "closes_at": classroom.when(session.closes_at),
        "steps": [s.name for s in p.brief.steps],
        "students": [s.model_dump(mode="json") for s in p.students],
        "alerts": [a.model_dump(mode="json") for a in p.alerts],
        "patterns": [pt.model_dump() for pt in p.patterns],
        "notable": [n.model_dump(mode="json") for n in p.notable],
    }


async def _outcomes_card(db: AsyncSession, session: Session) -> dict:
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    klass = await db.get(Class, session.class_id)
    out_of = sum(c.max for c in brief.assessment)
    rows = (
        await db.scalars(
            select(LessonOutcome)
            .where(LessonOutcome.session_id == session.id)
            .order_by(LessonOutcome.created_at)
        )
    ).all()
    p = await classroom.pulse(db, session)
    took_part = any(s.turns > 0 for s in p.students)
    names = {s.student_id: s.pseudonym for s in p.students}
    outcomes = sorted(
        (
            {
                "id": str(o.id),
                "student_id": str(o.student_id),
                "pseudonym": names.get(o.student_id, "unknown"),
                "status": o.status,
                "suggested": o.suggested,
                "suggested_total": o.suggested_total,
                "confirmed": o.confirmed,
                "confirmed_total": o.confirmed_total,
                "comment": o.comment,
                "out_of": out_of,
            }
            for o in rows
        ),
        key=lambda o: o["pseudonym"],
    )
    have = {o["student_id"] for o in outcomes}
    summary = await db.scalar(
        select(ClassInsight.summary)
        .where(ClassInsight.session_id == session.id)
        .order_by(ClassInsight.created_at.desc())
        .limit(1)
    )
    return {
        "type": "outcomes",
        "session_id": str(session.id),
        "title": brief.title or contract.title,
        "class_label": klass.label if klass else "",
        "status": session.status,
        "summary": summary,
        "criteria": [c.model_dump() for c in brief.assessment],
        "outcomes": outcomes,
        "students_without_outcome": [
            s.pseudonym
            for s in p.students
            if str(s.student_id) not in have and s.state != "not_started"
        ],
        # Nothing to judge is different from nothing judged yet; the card says which.
        "took_part": took_part,
        "can_suggest": (
            session.status == SessionStatus.CLOSED.value and bool(brief.assessment) and took_part
        ),
    }


async def build_card(db: AsyncSession, teacher: User, card: dict | None) -> dict | None:
    """Fill in a card the agent or a button asked for; None if its record has gone."""
    if not card:
        return None
    kind = card.get("type")
    if kind == "lessons":
        return await lessons_card(db, teacher)
    if kind == "lesson":
        lesson = await db.get(LessonContract, uuid.UUID(card["lesson_id"]))
        if lesson is None or lesson.teacher_id != teacher.id or lesson.archived_at is not None:
            return None
        return await _lesson_card(db, teacher, lesson)
    session = (
        await db.get(Session, uuid.UUID(card["session_id"])) if card.get("session_id") else None
    )
    if session is None:
        return None
    klass = await db.get(Class, session.class_id)
    if klass is None or klass.teacher_id != teacher.id:
        return None
    if kind == "class":
        return await _class_card(db, session)
    if kind == "student":
        student = await db.get(User, uuid.UUID(card["student_id"]))
        if student is None:
            return None
        view = await classroom.student_view(
            db, session, student, conversation=bool(card.get("conversation"))
        )
        return {"type": "student", "session_id": str(session.id), **view}
    if kind == "outcomes":
        return await _outcomes_card(db, session)
    return None


# ---------- the strip: who needs the teacher, in one line ----------


async def strip(db: AsyncSession, teacher: User) -> list[dict]:
    """One row of counts per lesson running now."""
    rows = []
    for session in await _live(db, teacher):
        p = await classroom.pulse(db, session)
        klass = await db.get(Class, session.class_id)
        first: dict[uuid.UUID, classroom.Alert] = {}
        for a in p.alerts:
            first.setdefault(a.student_id, a)
        rows.append(
            {
                "session_id": str(session.id),
                "title": p.brief.title,
                "class_label": klass.label if klass else "",
                "status": session.status,
                "closes_at": classroom.when(session.closes_at),
                "counts": dict(Counter(s.state for s in p.students)),
                "students": len(p.students),
                "needs_you": [
                    {
                        "exception_id": str(a.id),
                        "student_id": str(a.student_id),
                        "pseudonym": a.pseudonym,
                        "kind": a.kind,
                        "summary": a.summary,
                    }
                    for a in list(first.values())[:4]
                ],
                "needs_you_more": max(0, len(first) - 4),
            }
        )
    return rows
