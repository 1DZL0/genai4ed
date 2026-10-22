"""The teacher's one conversation with the class agent: the prompt, what the agent is
shown, the turn, and saving the brief it drafts. The agent chooses what to show and the
server builds the card from records; anything that changes state is a button the teacher
presses, or something they told the agent to do in so many words.

The lesson records are in `lessons`, and the cards built from them in `cards`.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import approaches, classroom, store, supervisor
from app.agent.brief import LessonBrief
from app.agent.lessons import (
    classes_of,
    current_version,
    draft_to_work_on,
    is_empty_draft,
    latest_versions,
    live_sessions,
    materials_of,
    new_lesson,
)
from app.agent.llm import (
    LLMClient,
    LLMError,
    ask_structured,
    bare_schema,
    image_part,
)
from app.agent.policy import PolicyRules, from_teachers_words
from app.enums import (
    ConflictCode,
    ContractStatus,
    ConversationKind,
    LeakageCheck,
    MessageRole,
    SessionStatus,
    ValidationOutcome,
)
from app.models import (
    AgentTurn,
    Class,
    ClassInsight,
    LessonContract,
    Material,
    Message,
    Session,
    User,
)

POLICY_VERSION = "class-agent-v1"
WINDOW = 24
MATERIAL_CHARS = 24_000

SYSTEM = """\
Who you are
You are the class agent. This is your one conversation with a teacher. You shape a lesson with \
them, teach it to each of their students one to one on their behalf, and report on it when \
asked. The teacher is the instructional authority: the lesson is theirs, in their words, steps, \
order and questions. You fill gaps, say so, and ask; you never redesign.

How to talk
Reply in "reply" like a colleague, not a form, in the same shape every time: one line on what \
you did and what you filled in yourself ("Drafted it with your four steps as you wrote them; I \
added the finish lines and the depth targets, so check those on the card"); then, each on its \
own numbered line, the one or two things you still need, each a choice with your default so \
they can answer in a word; last, what they can say or press. Nothing that is already on the \
card goes in the reply: not the steps, not the answers, not the rules as a list. Fresh words \
each turn, never a questionnaire, never a question they have answered or their material \
answers; if a question of yours goes unanswered twice, take your default and stop asking. \
Plain words a teacher uses: "set", "still to decide", "on the card"; never "compiled" or \
"unset". Under 600 characters: three or four short lines, shorter when their message was \
short. Never explain how you will teach or what the platform does unless asked; the card shows \
it.

What goes on the card
Choose with "show": "lesson" when you create, change or discuss a lesson; "lessons" for what \
they have; "class" for a running or finished lesson; "student" for one student, with the \
pseudonym in "student_ref" as the class data spells it; "outcomes" after a lesson has ended; \
"nothing" when a sentence is the whole answer. "lesson_ref" (title or id) names a lesson other \
than the one in focus; a brief in the same reply is saved to that lesson, so set it only when \
the brief is for it.

Designing a lesson together
Draft first, ask second. When they describe a lesson or attach material, draft it in that same \
reply from their words, fill in only what they left out, and name every part you filled in \
under "to_check" in the brief, so the card marks it until they confirm it or approve. When \
they give only a topic, draft a sketch: title, time, and two to four step headings with one \
real question each, and say it is a sketch for them to shape. Then build it up turn by turn, \
two things a turn at most, asking only what changes the teaching: the students and the time; \
what they should be able to do; the finish line for each step (what counts as done, which every \
step needs before approval); the depth each step asks for; help (hints or none, a worked step \
after how many tries, the answer never or after some, help in a fixed order, whether you may \
write their work, your own examples or only theirs); which signals they want told about at \
once and which kept in the record; and the end: marks against criteria, or a summary and a \
note on each student. Take defaults for everything else and say so. Below, the platform lists \
what the lesson still needs, in order: ask about the first two. Keep their wording in \
questions, criteria and rules. Suggest a change to a step as a question, and keep it out of \
the brief until they say yes; never restructure, reword, add or remove steps unless they ask. \
Anything in their material worth an activity: offer it, don't add it.
Depth targets: give every step a target depth from 1 to 4 (1 recall; 2 apply a method or \
explain a concept; 3 justify, compare or use evidence; 4 extended reasoning) from its goal, \
with later steps at least as deep as earlier ones, and at least one step at 3 when the \
objectives ask for understanding. Say the targets once, in one line, when you draft; the \
teacher can change any of them.

The brief and the rules
Return "brief" whole whenever the lesson is made or changed, including by an answer of theirs; \
a reply with no brief saves nothing, and a brief replaces the stored lesson, so never return \
only the changed part. The schema describes every field. Keep the title stable unless they \
rename it, and "subject" and "topics" as stored, because the platform uses them to tell a \
change from a new lesson; set "new_lesson" true only for a new lesson, with a different title. \
A change to an approved lesson makes a new version that needs approving again, so say so. \
Compile their sentences about help and conduct into "rules" and keep the sentences themselves \
in "rules_text": their sentences win over your numbers, so make the two agree. Compile only \
what they said, never a limit, an escalation or a rule they did not state; while a question of \
yours is unanswered leave that rule at its default; when a rule is ambiguous, take the stricter \
reading and say so. A new lesson starts with default rules and an empty rules_text unless they \
stated rules for it; never carry over another lesson's rules.

Running a lesson
You cannot approve, start, pause, resume or end a lesson, send or mark anything, confirm an \
outcome or write the summary. The platform does the first five, only when the teacher's latest \
message says so in so many words (approve; start, run, launch, begin, kick off; pause; resume, \
unpause, continue, carry on; end, stop, finish, close, wrap up), never from an earlier message \
or a bare "yes"; the rest are the teacher's buttons (Confirm and Write the summary on the \
outcomes card). Put what they asked for in "do", in order, with the class label in "class_ref" \
when they named one, and say "Approving it now", never that it is done. When they have not \
asked, leave "do" empty and give them the words ("start it with 10B") or the button. Any \
sentence that claims you did or will do one of these is struck out by the platform. To tell a \
student something, or change how one student is taught (move them on, show them the answer, \
take a break), put it in "guide": {"student_ref": the pseudonym as the class data spells it, \
"text": what they asked, in their words}; the agent teaching that student writes to them \
straight away, so say you are passing it on now. That is your only way to reach a student, and \
only in a lesson that is running. You speak only when written to: never promise to report back \
or to watch for something.

Teaching approaches
A lesson may be tagged to be taught by direct instruction or by guided inquiry ("approach" in \
their lessons). The teacher sets it on the card (the Taught by row, the approach tiles under \
the starters, or Make the other version), never you: when asked, say which to press. A lesson \
listed as approved is ready to start; it is running only when the class data says so.

Looking at the class, and after it
Use only the data below and ordinary school subject knowledge. Describe students by pseudonym, \
as observations of what they did ("kept asking for the answer"), never as claims about intent. \
Say only what the class data shows: do not name students with no turns, give their number \
("three have not started"), unless the data shows an alert for one (they pressed Ask my \
teacher before writing): name them and say that. One with no judged work has no misconception, \
and a lesson is finished only when its status says closed. When asked who needs attention, \
name everyone the data flags and nobody it doesn't. When several students share a difficulty, \
say so with the numbers and offer a follow-up activity as a new lesson once they say yes. After \
the end, "outcomes" shows the summary and the note on each student, which come from the Write \
the summary button; confirming each with its comment is the teacher's, and a student sees a \
result only once confirmed.
"""


Action = Literal["approve", "run", "pause", "resume", "end"]

# The words a teacher uses for each thing the agent may do when told to. Looked for in the
# teacher's message before anything is done, and in the reply so that saying so is not
# taken for a false claim.
# ponytail: English keywords only; a teacher who words it another way still has the buttons.
_SAID: dict[str, re.Pattern[str]] = {
    "approve": re.compile(r"\bapprov", re.IGNORECASE),
    "run": re.compile(r"\b(?:start|run|launch|begin|kick off)", re.IGNORECASE),
    "pause": re.compile(r"\bpaus", re.IGNORECASE),
    "resume": re.compile(r"\b(?:resum|unpaus|continu|carry on)", re.IGNORECASE),
    "end": re.compile(r"\b(?:end|stop|finish|clos|wrap up)", re.IGNORECASE),
}


class GuideOut(BaseModel):
    """What the teacher asked to be passed to one student's agent."""

    student_ref: str = Field(
        min_length=1, max_length=64, description="The pseudonym, as the class data spells it."
    )
    text: str = Field(
        min_length=1, max_length=1000, description="What the teacher asked, in their words."
    )


class TeacherTurnOut(BaseModel):
    """One reply to the teacher, with what it shows and what it saves."""

    reply: str = Field(
        min_length=1,
        max_length=2000,
        description="What the teacher reads, in the shape How to talk gives.",
    )
    show: Literal["nothing", "lesson", "lessons", "class", "student", "outcomes"] = Field(
        default="nothing", description="The card to put on screen."
    )
    lesson_ref: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "The title or id of a lesson other than the one in focus, when it is about that one."
        ),
    )
    student_ref: str | None = Field(
        default=None,
        max_length=64,
        description="The pseudonym, as the class data spells it, when show is student.",
    )
    brief: LessonBrief | None = Field(
        default=None,
        description="The whole lesson as it should now be, only when it was made or changed.",
    )
    new_lesson: bool = Field(
        default=False,
        description="True only for a new lesson rather than a change to the one in focus.",
    )
    do: list[Action] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "What the teacher's latest message asked the platform to do, in order: approve, "
            "run, pause, resume, end. Empty unless they said so in so many words. The server "
            "does it, not you."
        ),
    )
    class_ref: str | None = Field(
        default=None, max_length=64, description="The class label they named, when do has run."
    )
    guide: GuideOut | None = Field(
        default=None,
        description=(
            "A message for one student's agent, when the teacher asked you to tell a student "
            "something or to change how they are taught."
        ),
    )


def _version() -> str:
    """The name of exactly this wording: the prompt and the reply schema."""
    text = json.dumps(
        {"system": SYSTEM, "schema": bare_schema(TeacherTurnOut.model_json_schema())},
        sort_keys=True,
    )
    return "teacher-v14-" + hashlib.sha256(text.encode()).hexdigest()[:8]


PROMPT_VERSION = _version()


_ASKS_NEW = re.compile(
    r"\b(?:new|another|separate|second|next) lesson\b"
    r"|\bfollow[- ]?up (?:lesson|activity|session)\b",
    re.IGNORECASE,
)


async def _active_elsewhere(db: AsyncSession, teacher: User, session: Session) -> set[str]:
    """Students of this teacher who worked in another of their lessons today: the agent may
    rightly talk about them even when they have not started the one in focus."""
    since = datetime.now(UTC) - timedelta(hours=12)
    rows = await db.scalars(
        select(User.pseudonym)
        .join(AgentTurn, AgentTurn.student_id == User.id)
        .join(Session, Session.id == AgentTurn.session_id)
        .join(Class, Class.id == Session.class_id)
        .where(
            Class.teacher_id == teacher.id,
            Session.id != session.id,
            AgentTurn.created_at >= since,
        )
        .distinct()
    )
    return set(rows.all())


class ThreadUnavailable(Exception):
    """The model couldn't answer. The teacher's message is kept."""


# What a lesson version's status means, in the words the model is shown.
_STATUS_WORDS = {"draft": "draft", "active": "approved", "closed": "an earlier version"}


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
                taught = await db.get(LessonContract, session.contract_id)
                # The class keeps the version it started on; a change goes to the lesson as it
                # stands now, and a removed lesson is not brought back by talking about its run.
                lesson = await current_version(db, taught.plan_id) if taught else None
                return Focus(lesson, session)
        if lesson_id:
            lesson = await db.get(LessonContract, uuid.UUID(str(lesson_id)))
            if lesson is not None and lesson.teacher_id == teacher.id:
                current = await current_version(db, lesson.plan_id)
                return Focus(current, None) if current is not None else Focus()
    live = await live_sessions(db, teacher)
    if live:
        taught = await db.get(LessonContract, live[0].contract_id)
        lesson = await current_version(db, taught.plan_id) if taught else None
        return Focus(lesson, live[0])
    return Focus()


# Words too common in lesson titles to say which lesson is meant.
_TITLE_STOP = {
    "lesson",
    "lessons",
    "with",
    "from",
    "into",
    "about",
    "your",
    "their",
    "year",
    "maths",
}


def _title_words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", title.lower()) if len(w) >= 4 and w not in _TITLE_STOP}


async def _named(db: AsyncSession, teacher: User, text: str) -> LessonContract | None:
    """The one lesson of theirs the teacher names in this message, if they name one clearly:
    two of its title's words, or every word of a short title. A tie names none."""
    said = set(re.findall(r"[a-z]+", text.lower()))
    scored = []
    for lesson in await latest_versions(db, teacher):
        words = _title_words(lesson.title)
        hits = len(words & said)
        if words and (hits >= 2 or hits == len(words)):
            scored.append((hits, lesson))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


async def _resolve(db: AsyncSession, teacher: User, ref: str | None, focus: Focus):
    """The lesson the teacher means: an id, a title, or the one in focus."""
    if not ref:
        return focus.lesson
    try:
        found = await db.get(LessonContract, uuid.UUID(ref))
        if found is not None and found.teacher_id == teacher.id:
            # An id names the lesson; the change goes to it as it stands now, never to an older
            # version or a removed one.
            return await current_version(db, found.plan_id) or focus.lesson
    except ValueError:
        pass
    wanted = ref.strip().lower()
    lessons = await latest_versions(db, teacher)
    for lesson in lessons:
        if lesson.title.strip().lower() == wanted:
            return lesson
    for lesson in lessons:
        if wanted in lesson.title.strip().lower():
            return lesson
    return focus.lesson


# ---------- what the agent is shown ----------


async def _system(db: AsyncSession, teacher: User, focus: Focus) -> tuple[str, dict]:
    """The prompt and the manifest of what went into it."""
    lessons = await latest_versions(db, teacher)
    live = await live_sessions(db, teacher)
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
                    "status": _STATUS_WORDS.get(c.status, c.status),
                    "steps": len((c.brief or {}).get("steps") or []),
                    "unit": c.unit,
                    "approach": c.approach,
                }
                for c in lessons
            ]
        )
    )
    parts.append(
        "\nTheir classes:\n"
        + json.dumps([{"label": k.label, "students": n} for k, n in await classes_of(db, teacher)])
    )

    if focus.lesson is not None:
        brief = LessonBrief.model_validate(focus.lesson.brief or {})
        parts.append(
            f"\nThe lesson in focus is id {focus.lesson.id} ({focus.lesson.status}, "
            f"version {focus.lesson.version}).\nThe lesson in focus:\n" + brief.model_dump_json()
        )
        needed = brief.missing()
        if needed:
            parts.append(
                "\nStill needed before it can be approved, in order: "
                + "; ".join(needed)
                + ". Ask about the first two."
            )
        else:
            parts.append("\nNothing is still needed: the lesson can be approved as it stands.")
        if brief.steps and brief.duration_minutes / len(brief.steps) < 4:
            parts.append(
                f"\nTime check: {len(brief.steps)} steps in {brief.duration_minutes} minutes "
                "is under four minutes a step; say so, and offer to drop or merge one."
            )
        parts.extend(await _what_went_before(db, teacher, focus.lesson, brief))
        if focus.lesson.approach:
            parts.append("\n" + approaches.drafting(focus.lesson.approach))
            manifest["approach"] = focus.lesson.approach
            manifest["approach_version"] = approaches.VERSION
        materials = await materials_of(db, focus.lesson.plan_id)
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
    # A class running now is always in view, whatever card is open: its alerts, a wellbeing
    # one above all, must reach the teacher while they prepare another lesson.
    for running in _besides(live, focus):
        data, class_manifest = await classroom.snapshot(db, running)
        manifest.setdefault("running", []).append(class_manifest)
        taught = await db.get(LessonContract, running.contract_id)
        parts.append(
            f"\nAlso running now, though it is not the card in focus: session id {running.id} "
            f"({running.status}), being taught “{taught.title if taught else ''}”. Its needs_you "
            "alerts are the teacher's whatever they are working on.\nThat class right now:\n"
            + json.dumps(data)
        )
    return "\n".join(parts), manifest


def _besides(live: list[Session], focus: Focus) -> list[Session]:
    """The running lessons other than the one in focus."""
    return [s for s in live if focus.session is None or s.id != focus.session.id]


async def _what_went_before(
    db: AsyncSession, teacher: User, lesson: LessonContract, brief: LessonBrief
) -> list[str]:
    """Two things the record already knows that help the drafting: how this lesson went the
    last time it was taught, and the rules this teacher usually sets."""
    parts: list[str] = []
    last = await db.scalar(
        select(Session)
        .join(LessonContract, LessonContract.id == Session.contract_id)
        .where(
            LessonContract.plan_id == lesson.plan_id,
            Session.status == SessionStatus.CLOSED.value,
        )
        .order_by(Session.closed_at.desc().nulls_last(), Session.created_at.desc())
        .limit(1)
    )
    if last is not None:
        klass = await db.get(Class, last.class_id)
        summary = await db.scalar(
            select(ClassInsight.summary)
            .where(ClassInsight.session_id == last.id)
            .order_by(ClassInsight.created_at.desc())
            .limit(1)
        )
        pulse = await classroom.pulse(db, last)
        wrote = await classroom.students_who_wrote(db, last.id)
        finished = sum(1 for s in pulse.students if s.state == "finished")
        when = last.closed_at.date().isoformat() if last.closed_at else "earlier"
        line = (
            f"\nHow this lesson went last time, with {klass.label if klass else 'a class'} on "
            f"{when}: {len(wrote)} took part, {finished} finished."
        )
        if summary:
            line += f" The summary then: {summary.strip()}"
        if pulse.patterns:
            slips = "; ".join(f"{p.note} ({len(p.students)} students)" for p in pulse.patterns[:2])
            line += f" Common slips: {slips}."
        parts.append(line + " Use it when they ask what to change, not unasked.")
    default_rules = brief.rules == PolicyRules() and not brief.rules_text.strip()
    if lesson.status == ContractStatus.DRAFT.value and default_rules:
        usual = await db.scalar(
            select(LessonContract)
            .where(
                LessonContract.teacher_id == teacher.id,
                LessonContract.plan_id != lesson.plan_id,
                LessonContract.status == ContractStatus.ACTIVE.value,
                LessonContract.archived_at.is_(None),
            )
            .order_by(LessonContract.activated_at.desc().nulls_last())
            .limit(1)
        )
        if usual is not None:
            theirs = LessonBrief.model_validate(usual.brief or {})
            if theirs.rules != PolicyRules() or theirs.rules_text.strip():
                parts.append(
                    "\nThis teacher's usual rules, from their last approved lesson, to offer "
                    "as the default in one line: " + " ".join(theirs.rules.describe())
                )
    return parts


async def _history(db: AsyncSession, conversation, materials: list[Material]) -> list[dict]:
    """The recent thread as model messages, with attached images inline. The agent's earlier
    replies are shown in the shape it must answer in: shown as plain words, a model carries on
    in plain words and the reply has to be redone."""
    images = {str(m.id): m for m in materials if m.media_type.startswith("image/")}
    out: list[dict] = []
    for m in await store.messages(db, conversation.id, limit=WINDOW, said_only=True):
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
            said = json.dumps({"reply": m.text}, ensure_ascii=False)
            out.append({"role": "assistant", "content": said})
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
    for other in await latest_versions(db, teacher):
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
        session = next(iter(await live_sessions(db, teacher)), None)
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
    # A lesson they name by title is the one shown to the agent, even in a fresh conversation.
    named = await _named(db, teacher, text)
    if named is not None and (focus.lesson is None or named.plan_id != focus.lesson.plan_id):
        focus = Focus(named, None)
    system, manifest = await _system(db, teacher, focus)
    materials = await materials_of(db, focus.lesson.plan_id) if focus.lesson else []
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
    request["retry_reason"] = result.retry_reason

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

    # The model cannot decide to act: only what this message asked for is done.
    asked = [a for a in dict.fromkeys(out.do) if _SAID[a].search(text)]
    conflicts: list[str] = []
    guided = out.guide.student_ref.lower() if out.guide else None
    claimed = [
        sentence
        for sentence in supervisor.claims_teacher_action(out.reply)
        if not any(_SAID[a].search(sentence) for a in asked)
        # Passing the teacher's words on to that student is the agent's to do.
        and not (guided and guided in sentence.lower())
    ]
    if claimed:
        out.reply = supervisor.without_claims(out.reply, claimed, _next_button(focus))
        out.show = "class" if focus.session is not None else "lesson"
        conflicts.append(ConflictCode.FALSE_CLAIM.value)

    # Nothing may be said about a student who has not said anything yet, in any class shown.
    in_view = ([focus.session] if focus.session is not None else []) + _besides(
        await live_sessions(db, teacher), focus
    )
    silent: set[str] = set()
    for shown in in_view:
        silent |= {
            s.pseudonym
            for s in (await classroom.pulse(db, shown)).students
            if s.turns == 0 and not s.open_alerts
        } - await _active_elsewhere(db, teacher, shown)
    if silent:
        invented = supervisor.names_without_evidence(out.reply, silent)
        if invented:
            kept = [supervisor.strike(out.reply, invented)]
            # By name: "nobody has started" is false once anyone else in the class has.
            named = sorted(n for n in silent if any(n.lower() in s.lower() for s in invented))
            who = " and ".join(filter(None, [", ".join(named[:-1]), named[-1]]))
            kept.append(
                "I can only go on what students have actually done, and "
                f"{who} {'have' if len(named) > 1 else 'has'} not started yet."
            )
            out.reply = "\n".join(k for k in kept if k)
            conflicts.append(ConflictCode.FALSE_CLAIM.value)

    if conflicts:
        turn.conflicts = conflicts
        turn.validation_outcome = ValidationOutcome.REGENERATED.value

    force_new = force_new or (bool(_ASKS_NEW.search(text)) and not is_empty_draft(focus.lesson))
    changed = await _apply_brief(db, teacher, out, focus, said=text, force_new=force_new)
    card = await _chosen_card(db, teacher, out, focus, changed)
    data: dict = {"card": card} if card else {}
    if asked:
        data["do"] = asked
        if out.class_ref:
            data["class_ref"] = out.class_ref
    if out.guide:
        data["guide"] = out.guide.model_dump()
    reply = await store.add_message(
        db,
        conversation,
        role=MessageRole.AGENT,
        text=out.reply,
        data=data,
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


# ---------- the strip: who needs the teacher, in one line ----------
