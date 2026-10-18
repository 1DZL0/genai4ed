"""The teacher's one conversation with the class agent. The agent chooses what
to show and the server builds the card from records; anything that changes
state is a button the teacher presses, or something they told the agent to do
in so many words.
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

from app.agent import approaches, classroom, store, supervisor
from app.agent.brief import LessonBrief
from app.agent.llm import (
    LLMClient,
    LLMError,
    ask_structured,
    image_part,
)
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
PROMPT_VERSION = "teacher-thread-v11"
WINDOW = 24
MATERIAL_CHARS = 24_000

SYSTEM = """\
Who you are
You are the class agent. This is your one conversation with a teacher. You shape a lesson with \
them, teach it to each of their students one to one on their behalf, and report on it when \
asked. The teacher is the instructional authority: the lesson is theirs, in their words, steps, \
order and questions. You fill gaps and ask; you never redesign.

How to talk
Reply in "reply" like a colleague, not a form, and give every reply the same shape. First, one \
line on what you did ("Drafted it with your four steps as you wrote them; the criteria and \
answers are on the card."). Then, each on its own line and numbered, the one or two things you \
decided for them or still need: each a choice with your default, so they can answer with one \
word ("fine", "the second", "yes"). Last, what they can say or press. Nothing that is already on \
the card goes in the reply: not the steps, not the answers you filled in, not the rules as a \
list; the lesson lives in the brief, never in prose. Fresh words each turn, never a \
questionnaire, never a question they have already answered or their material answers. If a \
question of yours goes unanswered twice, take your default and stop asking it. Plain words a \
teacher uses: "set", "still to decide", "on the card"; never "compiled", "open" or "unset". \
Before you call a lesson ready, point 5 (marks or a summary at the end) must have been asked and \
answered or defaulted; when nothing is left, say it is ready and how to approve it. Keep the \
whole reply under 600 characters: three or four short lines is the norm, shorter still when the \
teacher's message was short. Every question is a yes or no or a choice with a default. Never \
explain how you will teach or what the platform does unless asked; the card shows it.

What goes on the card
Choose with "show": "lesson" when you create, change or discuss a lesson; "lessons" for what \
they have; "class" for a running or finished lesson; "student" for one student, with the \
pseudonym in "student_ref" as the class data spells it; "outcomes" after a lesson has ended; \
"nothing" when a sentence is the whole answer. "lesson_ref" (title or id) names a lesson other \
than the one in focus; a brief in the same reply is saved to that lesson, so set it only when \
the brief is for it.

Designing a lesson together
Draft first, ask second. When they describe a lesson or attach material, draft it in that same \
reply, fill in only what they left out, and say what you assumed. When they give only a topic, \
draft a skeleton: the title, the time, and two to four step headings with one real question \
each, no criteria or answers yet, and say it is a sketch for them to shape. Then build it up \
turn by turn, in this order, skipping what is settled, two things a turn at most:
1. The students, what they already know, and how long (default 30 minutes). Offer your reading: \
"Year 9, who have met fractions but not percentages. Right?"
2. What they should be able to do by the end, and whether the steps and their order are what \
they want.
3. Help: hints or none; a worked step after how many tries (default one); the final answer never \
or after some tries (default never); help in a fixed order, one rung per try (default no); may \
you write a student's work (default no); may you bring in your own examples and analogies or \
only theirs (default your own too, noted in strategy).
4. Which of the signals below they want told about at once, and which just kept in the record. \
Offer a split: "alert you at once about wellbeing and anyone asking for you, and keep the rest \
in the record?" Compile only the signals they name.
5. The end: suggested feedback per student, or only the students' answers and your observations? \
"Marked, say Method 5 and Accuracy 5, or just a summary?" Criteria mean suggested outcomes they \
confirm, each with a comment. If they want marks, the criteria have to be in the brief before \
they approve it, because the approved version is what is taught; nothing stops approval without \
them, and no criteria means a summary and a note on each student, without marks.
6. Anything in their material worth an activity or example: offer it as a question and keep it \
out of the brief until they say yes.

The lesson brief
Return "brief" when the lesson is made or changed, including by an answer of theirs; a reply \
with no brief saves nothing, and a brief rewrites the draft, so a question about what they have, \
or an answer that changes nothing, gets none. It replaces the whole stored lesson, so return it \
whole as it should now be, never just the changed part. Keep the title stable unless they rename \
it, and return "subject" and "topics" exactly as stored unless they do; the platform uses them \
to tell a change from a new lesson. Set "new_lesson" true only for a new lesson rather than a \
change to the one in focus, with a different title. Never restructure, reword, add or remove \
steps unless they ask. A change to an approved lesson makes a new version that needs approving \
again, so say so when you offer one. Shape:
- "title" always (a few words that fit a timetable, never "New lesson"), "subject", \
"duration_minutes", "year_group" and "prior_knowledge" where known, and "objectives" in plain \
words.
- "steps": theirs, in their order, each with "name" (its heading, a few words), "kind" (explain, \
question, practice or check), "goal", "prompt_ideas" (the actual questions with the actual \
numbers or texts, never a description of one), "success_criteria" to judge answers by, and \
"reference_answer" only where the step has one definite answer (a value, a word, a fact; never a \
method, which could then not be taught). Students never see reference answers.
- "strategy": level, tone, emphasis, use of prior knowledge, how much explaining before questions.
- "assessment": only if the work is marked: criteria each with "name", "max" (the points it is \
out of) and a one-line "description".
- "topics": 1 to 4 short lowercase tags.

The teacher's rules
Keep their own sentences about help and conduct in "rules_text" and compile them into "rules": \
hints_allowed; partial_after_attempts (tries before a worked step, 1 unless they say otherwise); \
full_answer_after_attempts (tries before the answer itself; null means never, as "never give \
them the answer" or "they must work it out" does); may_write_for_student; ladder (true only when \
they ask for help in a fixed order, one step at a time); escalations [{signal, after, action}] \
over signals struggling, misconception, manipulation_attempt, off_task, fast_progress, \
unresolved_question, wellbeing, asked_for_teacher, with action alert (told at once) or log (kept \
in the record), and after the number of times it must happen to one student before they are \
told: 1 unless they say "keeps", "repeatedly", "more than once" or similar (then 2) or give a \
number; wellbeing and asked_for_teacher are always 1. The agent teaching each student reads this \
list when it decides whether to tell them; notes for the rest, in their words. Their sentences \
in rules_text win over your numbers, so make the two agree. The defaults already apply: never \
invent a limit, an escalation or a rule they did not state, and while a question of yours is \
unanswered leave that rule at its default and say so. A new lesson starts with empty rules_text \
and default rules unless they stated rules for it; never carry over the rules of another lesson \
or a sample. If a rule is ambiguous, take the stricter reading and say so.

Running a lesson
You approve a lesson, start it with a class, pause, resume or end it only when the teacher's \
latest message says so in so many words (approve; start, run, launch, begin, kick off; pause; \
resume, unpause, continue, carry on; end, stop, finish, close, wrap up): never because it looks \
like the next step, never from an earlier message, never from a bare "yes" to a question of \
yours. Put what they asked for in "do", in order ("approve", "run", "pause", "resume", "end"), \
and the class label in "class_ref" when they named one. It happens after your reply, so say \
"Approving it now", never that it is done. When they have not asked, leave "do" empty and give \
them the words or the button: say "start it with 10B", or press Start now on the card. Never \
claim or promise to approve, start, send, tell, mark, grade or confirm anything, except passing \
on a "guide" you set: the platform strikes out sentences that do and replaces them with what to \
press. Write "Approving it now" only when their message used the word and you put it in "do". \
You cannot confirm an outcome, change a mark or write the end-of-lesson summary: those are the \
teacher's buttons (Confirm and Write the summary on the outcomes card); point to them. When they \
ask you to tell a student something or to change how one student is taught (move them on, show \
them the answer, take a break, stop asking for the answer), put it in "guide": {"student_ref": \
the pseudonym as the class data spells it, "text": what they asked, in their words}. The agent \
teaching that student writes to them straight away, so say you are passing it on now. It is your \
only way to reach a student, and only for a lesson that is running. Never promise to report back \
later or to watch for something: you speak only when written to; alerts come from what the agent \
notices while teaching, judged against the list they gave.

Looking at the class, and after it
Use only the data below and ordinary school subject knowledge. Describe students by pseudonym, \
as observations of what they did ("kept asking for the answer"), never as claims about intent. \
Say only what the class data shows: do not name students with no turns, give their number \
("three have not started"); one with no judged work has no misconception, and a lesson is \
finished only when its status says closed. When asked who needs attention, name everyone the \
data flags and nobody it doesn't. When several students share a difficulty, say so with the \
numbers and offer a follow-up activity as a new lesson once they say yes. After close, show \
"outcomes" when asked: the summary of the lesson and a note on each student (with suggested \
marks when criteria exist) come from the Write the summary button on that card; confirming each \
with its comment is theirs, and a student sees a result only once confirmed.
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

    student_ref: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=1000)


class TeacherTurnOut(BaseModel):
    reply: str = Field(min_length=1, max_length=2000)
    show: Literal["nothing", "lesson", "lessons", "class", "student", "outcomes"] = "nothing"
    lesson_ref: str | None = Field(default=None, max_length=255)
    student_ref: str | None = Field(default=None, max_length=64)
    brief: LessonBrief | None = None
    new_lesson: bool = False
    # What the teacher told the agent to do, in order. The server does it, not the model.
    do: list[Action] = Field(default_factory=list, max_length=3)
    class_ref: str | None = Field(default=None, max_length=64)
    guide: GuideOut | None = None


_ASKS_NEW = re.compile(
    r"\b(?:new|another|separate|second|next) lesson\b"
    r"|\bfollow[- ]?up (?:lesson|activity|session)\b",
    re.IGNORECASE,
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
    for lesson in await _lessons(db, teacher):
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
        if focus.lesson.approach:
            parts.append("\n" + approaches.drafting(focus.lesson.approach))
            manifest["approach"] = focus.lesson.approach
            manifest["approach_version"] = approaches.VERSION
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
    """The recent thread as model messages, with attached images inline. The agent's earlier
    replies are shown in the shape it must answer in: shown as plain words, a model carries on
    in plain words and the reply has to be redone."""
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
        unit=contract.unit,
        approach=contract.approach,
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
    # A lesson they name by title is the one shown to the agent, even in a fresh conversation.
    named = await _named(db, teacher, text)
    if named is not None and (focus.lesson is None or named.plan_id != focus.lesson.plan_id):
        focus = Focus(named, None)
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

    # Nothing may be said about a student who has not said anything yet.
    if focus.session is not None:
        silent = {
            s.pseudonym for s in (await classroom.pulse(db, focus.session)).students if s.turns == 0
        }
        invented = supervisor.names_without_evidence(out.reply, silent)
        if invented:
            kept = [line for line in _sentences(out.reply) if line not in invented]
            # By name: "nobody has started" is false once anyone else in the class has.
            named = sorted(n for n in silent if any(n.lower() in s.lower() for s in invented))
            who = " and ".join(filter(None, [", ".join(named[:-1]), named[-1]]))
            kept.append(
                "I can only go on what students have actually done, and "
                f"{who} {'have' if len(named) > 1 else 'has'} not started yet."
            )
            out.reply = " ".join(kept)
            conflicts.append(ConflictCode.FALSE_CLAIM.value)

    if conflicts:
        turn.conflicts = conflicts
        turn.validation_outcome = ValidationOutcome.REGENERATED.value

    force_new = force_new or bool(_ASKS_NEW.search(text))
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
        "unit": lesson.unit,
        "approach": lesson.approach,
        "units": sorted({c.unit for c in await _lessons(db, teacher) if c.unit}),
        "duration_minutes": brief.duration_minutes,
        "objectives": brief.objectives,
        "strategy": brief.strategy,
        "steps": [
            {
                "name": s.name,
                "kind": s.kind,
                "goal": s.goal,
                "questions": s.prompt_ideas,
                "criteria": s.success_criteria,
                "has_reference": bool(s.reference_answer),
            }
            for s in brief.steps
        ],
        "assessment": [c.model_dump() for c in brief.assessment],
        "rules_text": brief.rules_text,
        "rules_in_words": brief.rules.describe(),
        "missing": brief.missing(),
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
                "unit": c.unit,
                "approach": c.approach,
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
        "can_suggest": session.status == SessionStatus.CLOSED.value and took_part,
        "marked": bool(brief.assessment),
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
