"""The teacher's one conversation with the class agent: what the agent is shown, the
turn, and saving the brief it drafts. The agent chooses what to show and the
server builds the card from records; anything that changes state is a button the teacher
presses, or something they told the agent to do in so many words.

The agent's fixed instructions are in `teacher_prompt`, the lesson records in `lessons`,
and the cards built from them in `cards`.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import (
    activities,
    approaches,
    classroom,
    store,
    supervisor,
)
from app.agent.brief import BriefServing, LessonBrief
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
    SendBackOnce,
    ask_structured,
    bare_schema,
    image_part,
)
from app.agent.policy import (
    PolicyRules,
    from_teachers_words,
    literal_rules,
    without_unsaid_counts,
)
from app.agent.teacher_prompt import SYSTEM
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
    "end": re.compile(
        r"\b(?:end|stop|finish|clos(?:e|ed|es|ing)(?!\s+(?:look|call|to|by|enough))|wrap up)",
        re.IGNORECASE,
    ),
}
# The same words used as nouns, or in phrases that order nothing: taken out of a sentence
# before it is read for an instruction ("from the start", "end up", "the finish line").
_NOT_AN_ORDER: dict[str, re.Pattern[str]] = {
    "run": re.compile(
        r"\b(?:the|a|from|at|since|before|after|until|till)\s+(?:the\s+)?(?:start|run|launch|beginning)\b",
        re.IGNORECASE,
    ),
    "end": re.compile(
        r"\b(?:the|at|by|until|till|towards?|before|after|near)\s+(?:the\s+)?end\b|\bend up\b"
        r"|\bfinish(?:ing)?\s+line\b|\bin the end\b|\bend of\b",
        re.IGNORECASE,
    ),
}
# A claim of starting or ending, which only a button does: "Starting it with 10B", "Ending it
# now". Not "press Start", "you could end it", "once you press End": those tell the teacher.
_BUTTON_CLAIM = re.compile(
    # The verb opens the clause, or follows the agent speaking of itself ("I'll end it") or a
    # joining word ("and starting it"); "the lesson running now" is a description, not a claim.
    r"(?:^|\b(?:I|I'm|I'll|I will|I am|I have|I've|we|we're|we'll|and|then|now|so)\s+)"
    r"(?:start|starting|started|run|running|launch\w*|begin\w*|kick(?:ing)? off|end|ending|"
    r"ended|stop\w*|finish\w*|clos(?:e|ing|ed)|wrap(?:ping)? up)\b\s+"
    r"(?:it\b|now\b|the (?:lesson|class)\b|this\b|with\b)",
    re.IGNORECASE,
)
_TELLS_THE_TEACHER = re.compile(
    r"\b(?:press|button|card|you can|you could|you may|when you|once you|if you)\b", re.IGNORECASE
)


def claims_a_button_action(sentence: str) -> bool:
    """Whether a sentence of the agent's claims to start or end a lesson itself. A question
    claims nothing: "End with marks, or a summary?" asks how the lesson should end."""
    if sentence.rstrip().endswith("?"):
        return False
    return bool(_BUTTON_CLAIM.search(sentence)) and not _TELLS_THE_TEACHER.search(sentence)


# A sentence that asks is not one that orders.
_ASKS = re.compile(
    r"^(?:who|what|when|where|why|how|which|whose|is|are|was|were|do|does|did|can|could|"
    r"shall|should|will|would|have|has|had|am|may|might)\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


# Words the teacher is quoting, not saying: a pupil's message pasted in to ask about it, a
# title. Taken out before a sentence is read for an instruction or a pupil's name.
_QUOTED = re.compile(r'"[^"\n]{2,}?"|“[^”\n]{2,}?”|‘[^’\n]{2,}?’|(?<!\w)\'[^\'\n]{2,}?\'(?!\w)')


def unquoted(text: str) -> str:
    """The teacher's own words, with anything they put in quotation marks taken out."""
    return _QUOTED.sub(" ", text or "")


# The actions words may ask for. Starting a class and ending one touch every pupil at once
# and cannot be undone, so they are buttons only: Start on the lesson card, End on the board.
WORD_ACTIONS = ("approve", "pause", "resume")


def asked_for(text: str) -> list[str]:
    """The actions the teacher's own words ask for, in `_SAID` order: an instruction in a
    sentence of theirs, never a question that happens to hold the verb ("Who hasn't started
    yet?"), never the word as a noun ("Worked steps from the start"), and never words they
    are quoting. Only WORD_ACTIONS; the rest are buttons."""
    found: list[str] = []
    for sentence in _SENTENCES.split(unquoted(text)):
        sentence = sentence.strip()
        if not sentence or sentence.endswith("?") or _ASKS.match(sentence):
            continue
        for action in WORD_ACTIONS:
            pattern = _SAID[action]
            if action in found:
                continue
            nouns = _NOT_AN_ORDER.get(action)
            cleaned = nouns.sub(" ", sentence) if nouns else sentence
            if pattern.search(cleaned):
                found.append(action)
    return [a for a in _SAID if a in found]


class GuideOut(BaseModel):
    """What the teacher asked to be passed to one student's agent."""

    student_ref: str = Field(
        min_length=1, max_length=64, description="The pseudonym, as the class data spells it."
    )
    text: str = Field(
        min_length=1, max_length=1000, description="What the teacher asked, in their words."
    )
    days: int | None = Field(
        default=None,
        ge=0,
        le=30,
        description=(
            "Only when the teacher wants it kept in mind across their lessons, such as 'this "
            "week' (7) or 'for the next two days' (2): for how many days, today included. The "
            "tutor then reads it in each of their lessons until then, from its next reply, and "
            "nothing is sent to the student. 0 takes back what was kept before. Null when it "
            "is for the lesson running now."
        ),
    )


_WHOLE_LESSON = "The whole lesson as it should now be, only when it was made or changed."


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
    brief: LessonBrief | None = Field(default=None, description=_WHOLE_LESSON)
    new_lesson: bool = Field(
        default=False,
        description="True only for a new lesson rather than a change to the one in focus.",
    )
    guess_answer: Literal["", "kept", "corrected"] = Field(
        default="",
        description=(
            "What the teacher's latest message did with your guess at the lesson's activity: "
            "kept (kept it in words) or corrected (corrected it). Empty when they carry on "
            "without a word about it."
        ),
    )
    guess_said: str = Field(
        default="",
        max_length=400,
        description="The sentence of your reply that says your guess at the kind, word for word.",
    )
    gave: Literal["", "topic", "part", "whole"] = Field(
        default="",
        description=(
            "How much of a lesson the teacher's own words have given so far, when they are "
            "asking for one: topic (only what it is about), part (some of what the students "
            "will do, with the rest left for you to build), whole (every step or question of "
            "the lesson, with nothing left to add). Empty on any other turn."
        ),
    )
    do: list[Action] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "What the teacher's latest message asked the platform to do, in order: approve, "
            "pause, resume. Empty unless they said so in so many words. Starting a lesson and "
            "ending one are buttons the teacher presses, so neither goes here. The server "
            "does it, not you."
        ),
    )
    class_ref: str | None = Field(
        default=None,
        max_length=64,
        description="Left empty: the teacher picks the class with the Start button.",
    )
    guide: GuideOut | None = Field(
        default=None,
        description=(
            "A message for one student's agent, when the teacher asked you to tell a student "
            "something or to change how they are taught."
        ),
    )


class TeacherTurnServing(TeacherTurnOut):
    # The reply the agent gives: its steps name the objective they serve. The agent reads the
    # class's own words, so they stay as they were.
    __doc__ = TeacherTurnOut.__doc__

    # The shape of the lesson the reply carries, which the agent is also shown the lesson in.
    lesson: ClassVar[type[LessonBrief]] = BriefServing

    brief: BriefServing | None = Field(default=None, description=_WHOLE_LESSON)


# "Where this lesson stands": the block the server writes into each turn's prompt from what it
# knows for certain about the lesson in focus. Its fixed sentences.
OPENS = "Where this lesson stands:"
STANDS_FOLLOW_UP = (
    "They pressed the button to follow up a shared difficulty: draft the new lesson now, and "
    "say your guess at its heading and kind in one line."
)
# Said last in the block. Run v26-switched: to a teacher whose screen had no headings, the
# agent still said "Pick a heading below".
STANDS_IN_WORDS = (
    "This teacher's screen has no activity box and no headings to press: the kind of activity "
    "is yours to guess from their words and theirs to keep or correct in words."
)
# Said of the agent's guess at the lesson's activity while the teacher has not spoken to it.
STANDS_UNSPOKEN = (
    "; they have not spoken to it yet, so set guess_answer when their message keeps it in "
    "words or corrects it"
)
# What a lesson that is not drafted yet waits for.
STANDS_THREE = (
    "A lesson that is new or has nothing drafted in it yet is drafted only once the teacher has "
    "given an objective, the students' age and the length: with any of the three missing, leave "
    "brief empty and ask for what is missing, two questions at most."
)
STANDS_THEN_GUESS = (
    "With all three, draft it and say your guess at the heading and kind in one line."
)
# Said of a lesson in focus that is drafted already. Runs v26-ask-3 and v26-ask-old-gaps: told
# the length of a draft that also lacked the age, the agent thanked the teacher and saved
# nothing while it waited for the age (answers-one, 5 of 10).
STANDS_DRAFTED = (
    "The lesson in focus is already drafted: what they give or change goes into brief in this "
    "reply."
)
# What such a draft is sent back with: one of the three is not in it, or its objectives are
# marked as the agent's own. A reason goes back cut to 600 characters, so the two together
# stay under that.
NOT_ALL_THREE = (
    "The draft has no {missing}. A lesson is drafted only once the teacher has given an "
    "objective, the students' age and the length. If their words do give what is missing, send "
    "the draft again with it filled in. If not, leave brief empty and ask for what is missing, "
    "two questions at most."
)
NOT_AGREED = (
    "You marked the objectives as your own in to_check. An objective goes on the card once the "
    "teacher wrote it or agreed to one you offered. If they did, send the draft again without "
    "objectives in to_check. If not, leave brief empty, offer two or three objectives in your "
    "question and wait for their answer."
)


# The block's fixed sentences, which the version covers.
STANDS = (
    STANDS_FOLLOW_UP,
    STANDS_IN_WORDS,
    STANDS_UNSPOKEN,
    STANDS_THREE,
    STANDS_THEN_GUESS,
    STANDS_DRAFTED,
    NOT_ALL_THREE,
    NOT_AGREED,
)


def _version(
    label: str,
    system: str,
    stands: tuple[str, ...],
    reply: type[TeacherTurnOut] = TeacherTurnServing,
) -> str:
    """The name of exactly this wording: the prompt, the reply schema, and the fixed sentences
    of the block the server writes each turn."""
    text = json.dumps(
        {
            "system": system,
            "schema": bare_schema(reply.model_json_schema()),
            "stands": list(stands),
        },
        sort_keys=True,
    )
    return label + hashlib.sha256(text.encode()).hexdigest()[:8]


# The name every reply is recorded under. It moves whenever the wording does.
PROMPT_VERSION = _version("teacher-v27-", SYSTEM, STANDS)


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


def _stands(focus: Focus, *, follow_up: bool) -> tuple[str, str]:
    """What the server knows for certain about the lesson in focus, as the block written into
    the turn's prompt, and the case it names for the record: the follow-up button, a lesson
    that is not drafted yet, or one that is. The agent judges only the teacher's words. A lesson
    that is not drafted yet waits for an objective, the age and the length."""
    if follow_up:
        return " ".join([OPENS, STANDS_FOLLOW_UP, STANDS_IN_WORDS]), "follow-up"
    said: list[str] = []
    brief = LessonBrief.model_validate(focus.lesson.brief or {}) if focus.lesson else None
    heading = activities.heading(brief.heading) if brief and brief.heading else None
    if brief is None:
        said.append("No lesson is in focus.")
    elif heading is None:
        said.append("The lesson in focus has no activity heading.")
    else:
        kind = brief.activity_kind.strip() or brief.listed_kind
        # A lesson from when headings could be pressed may still have one the teacher pressed.
        whose = "your guess" if brief.heading_from == "worked_out" else "which they pressed"
        with_kind = f', with the kind "{kind}"' if kind else ""
        done = {"kept_said": ", which they kept", "kept_silent": ", which they kept"}
        done["corrected"] = ", from their correction"
        state = done.get(brief.record.guess, STANDS_UNSPOKEN if brief.guessing else "")
        said.append(f"The lesson in focus is {heading.label}, {whose}{with_kind}{state}.")
    said += [STANDS_THREE, STANDS_THEN_GUESS]
    drafted = focus.lesson is not None and not is_empty_draft(focus.lesson)
    if drafted:
        said.append(STANDS_DRAFTED)
    return " ".join([OPENS, *said, STANDS_IN_WORDS]), "drafted" if drafted else "not drafted"


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


def _by_title(lessons: list[LessonContract], ref: str) -> LessonContract | None:
    """The lesson a title names: the one with exactly that title, else the first that holds it."""
    wanted = ref.strip().lower()
    for lesson in lessons:
        if lesson.title.strip().lower() == wanted:
            return lesson
    for lesson in lessons:
        if wanted in lesson.title.strip().lower():
            return lesson
    return None


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
    return _by_title(await latest_versions(db, teacher), ref) or focus.lesson


def _meant(lessons: list[LessonContract], ref: str | None, focus: Focus) -> LessonContract | None:
    """As `_resolve` reads it, from lessons already loaded: an id, a title, or the one in focus."""
    if not ref:
        return focus.lesson
    by_id = next((c for c in lessons if str(c.id) == ref.strip().lower()), None)
    return by_id or _by_title(lessons, ref) or focus.lesson


# ---------- what the agent is shown ----------


async def _system(
    db: AsyncSession,
    teacher: User,
    focus: Focus,
    fixed: str,
) -> tuple[str, dict]:
    """The prompt and the manifest of what went into it. `fixed` is the wording it opens with,
    the same on every turn. The lesson in focus is shown in the shape the agent's reply
    carries it back in."""
    lessons = await latest_versions(db, teacher)
    live = await live_sessions(db, teacher)
    parts = [fixed]
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
        brief = TeacherTurnServing.lesson.model_validate(focus.lesson.brief or {})
        parts.append(
            f"\nThe lesson in focus is id {focus.lesson.id} ({focus.lesson.status}, "
            f"version {focus.lesson.version}).\nThe lesson in focus:\n" + brief.for_agent()
        )
        needed = brief.missing()
        # A draft nothing is written into yet is asked about as a new lesson is, by the block
        # that closes the prompt: the objective first, not the title.
        waits = is_empty_draft(focus.lesson)
        if needed and not waits:
            parts.append(
                "\nStill needed before it can be approved, in order: "
                + "; ".join(needed)
                + ". Ask about the first two."
            )
        elif not needed:
            parts.append("\nNothing is still needed: the lesson can be approved as it stands.")
        if brief.steps and brief.duration_minutes and brief.duration_minutes / len(brief.steps) < 4:
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


def _teachers_words(message: Message) -> str:
    """A teacher's message as the agent reads it. One from when headings could be pressed
    holds a line saying which; the screen has none to press now, so the agent reads the words
    without it. A press sent alone was saved as the line alone: it stays as it was, the
    teacher's answer to the question before it, since a message with nothing in it is refused
    by the model and taking it out would leave that question unanswered."""
    line = activities.picked_line(message.data.get("picks") or [])
    if not line:
        return message.text
    words = "\n\n".join(p.strip() for p in message.text.split(line) if p.strip())
    return words or message.text


async def _history(db: AsyncSession, conversation, materials: list[Material]) -> list[dict]:
    """The recent thread as model messages, with attached images inline. The agent's earlier
    replies are shown in the shape it must answer in: shown as plain words, a model carries on
    in plain words and the reply has to be redone."""
    images = {str(m.id): m for m in materials if m.media_type.startswith("image/")}
    out: list[dict] = []
    for m in await store.messages(db, conversation.id, limit=WINDOW, said_only=True):
        if m.role == MessageRole.TEACHER.value:
            attached = [images[i] for i in m.material_ids if i in images]
            words = _teachers_words(m)
            out.append(
                {
                    "role": "user",
                    "content": (
                        [
                            {"type": "text", "text": words},
                            *[image_part(a.media_type, a.content) for a in attached],
                        ]
                        if attached
                        else words
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


def _turn(conversation_id, manifest, client, result, tries, request, *, version, session_id=None):
    """The audit row for one call to the model; `result` is None when it failed. `version` names
    the wording the call was made from."""
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
        prompt_version=version,
        provider=result.provider if result else client.name,
        model=result.model if result else client.model,
        latency_ms=result.latency_ms if result else 0,
        usage=result.usage if result else {},
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


def _not_drafted_yet(
    out: TeacherTurnOut, focus: Focus, theirs: list[LessonContract], *, asks_new: bool
) -> bool:
    """Whether the reply's brief would be written as a lesson that is not drafted yet: a new
    one, an empty draft, or a lesson other than the one it names, as `_apply_brief` decides."""
    if asks_new:
        return True
    base = _meant(theirs, out.lesson_ref, focus)
    if base is None or is_empty_draft(base):
        return True
    old = LessonBrief.model_validate(base.brief or {})
    # As when it is written: a change that names no title or subject keeps the ones it had.
    named = out.brief.model_copy(
        update={
            "title": out.brief.title.strip() or old.title,
            "subject": out.brief.subject.strip() or old.subject,
        }
    )
    return not _same_lesson(base, named, claimed_new=out.new_lesson)


def _lacks(
    out: TeacherTurnOut,
    focus: Focus,
    theirs: list[LessonContract],
    *,
    follow_up: bool,
    asks_new: bool,
) -> str:
    """What a draft of a lesson that is not drafted yet is sent back with, or nothing. It
    waits for an objective, the age and the length, and for objectives the agent has not marked
    as its own. The follow-up button and a change to a drafted lesson are left alone."""
    if out.brief is None or follow_up:
        return ""
    if not _not_drafted_yet(out, focus, theirs, asks_new=asks_new):
        return ""
    brief = out.brief
    given = any(o.strip() for o in brief.objectives)
    there = (
        ("objective", given),
        ("age", brief.age is not None),
        ("length", brief.duration_minutes is not None),
    )
    missing = [name for name, has in there if not has]
    reasons = []
    if missing:
        named = " or ".join(filter(None, [", ".join(missing[:-1]), missing[-1]]))
        reasons.append(NOT_ALL_THREE.format(missing=named))
    # An entry that names the objectives and no step: "objectives", "Learning objectives".
    marked = any("objective" in e.lower() and "step" not in e.lower() for e in brief.to_check)
    if given and marked:
        reasons.append(NOT_AGREED)
    return " ".join(reasons)


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


def _keep_activity(brief: LessonBrief, old: LessonBrief) -> None:
    """A change to a lesson keeps the server's record of its activity, which the agent never
    writes, and the heading and kind it had when the change comes back without them."""
    brief.record = old.record
    if not brief.heading:
        brief.heading = old.heading
    # A kind belongs to its heading: under a new heading the old kind is not carried across.
    if brief.heading == old.heading and not brief.activity_kind:
        brief.activity_kind, brief.listed_kind = old.activity_kind, old.listed_kind


def _answered_in_words(lesson: LessonContract | None, answer: str, words: str) -> None:
    """A teacher who keeps the agent's guess in words, or corrects it, on a turn that changes
    nothing else: the draft's record says so in place, since there is no new version to carry
    it. A correction with no new draft yet is still a correction."""
    if lesson is None or lesson.status != ContractStatus.DRAFT.value:
        return
    brief = LessonBrief.model_validate(lesson.brief or {})
    if brief.guessing:
        update = {"guess": "kept_said"}
        if answer == "corrected":
            update = {"guess": "corrected", "correction": words[:600]}
        brief.record = brief.record.model_copy(update=update)
        lesson.brief = brief.model_dump(mode="json")


def _note_the_guess(
    brief: LessonBrief, old: LessonBrief | None, *, answer: str, words: str, said: str
) -> None:
    """What the teacher did with the agent's guess at the activity, kept in the record. What
    their words did with it is the agent's to say ("kept" or "corrected"); a turn they carry
    on without a word keeps a standing guess. A verdict stands until they speak again: a
    rewording of the kind by the agent alone does not undo it. A new heading is a new guess."""
    now = brief.guessed()
    was = old.record.guess if old is not None else ""
    if old is not None and not was and old.guessing:
        was = "standing"
    new_guess = {"guess": "standing", "said": said[:400], "correction": ""}
    if not was:
        if not any(now):
            return
        update = new_guess
    elif answer == "corrected":
        update = {"guess": "corrected", "correction": words[:600]}
    elif answer == "kept":
        update = {"guess": "kept_said"}
    elif brief.heading != old.heading:
        update = new_guess if any(now) else {"guess": "", "said": "", "correction": ""}
    elif was == "standing":
        update = {"guess": "kept_silent"} if now[1] == old.guessed()[1] else new_guess
    else:
        return
    brief.record = brief.record.model_copy(update=update)


async def _apply_brief(
    db: AsyncSession,
    teacher: User,
    out: TeacherTurnOut,
    focus: Focus,
    *,
    said: str = "",
    choices: str = "",
    force_new: bool = False,
) -> LessonContract | None:
    """Write the brief the model returned into a draft, new or existing."""
    if out.brief is None:
        return None
    base = None if force_new else await _resolve(db, teacher, out.lesson_ref, focus)
    stored: PolicyRules | None = None
    old: LessonBrief | None = None
    if base is not None:
        # A change that comes back without a title or subject keeps the ones it had.
        old = LessonBrief.model_validate(base.brief or {})
        out.brief.title = out.brief.title.strip() or old.title
        out.brief.subject = out.brief.subject.strip() or old.subject
        out.brief.age = out.brief.age or old.age
        out.brief.activity = out.brief.activity or old.activity
        if not _same_lesson(base, out.brief, claimed_new=out.new_lesson):
            base = old = None
        else:
            stored = old.rules
    if old is not None:
        _keep_activity(out.brief, old)
    _note_the_guess(out.brief, old, answer=out.guess_answer, words=said, said=out.guess_said)
    if base is None:
        await _drop_carried_rules(db, teacher, out, said)
    # The teacher's own words outrank the model's reading of them.
    out.brief.rules = from_teachers_words(out.brief.rules, out.brief.rules_text)
    # And their own message, when it is the quick choices' sentence, whichever field the model
    # put the words in.
    out.brief.rules = literal_rules(out.brief.rules, said)
    if choices:
        # What they pressed is theirs outright, whatever the model made of it.
        out.brief.rules = from_teachers_words(out.brief.rules, choices)
    # A count none of their words gave is the model's, standing in for a setting that is not there.
    out.brief.rules = without_unsaid_counts(
        out.brief.rules, " ".join((out.brief.rules_text, said, choices)), keep=stored
    )
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
    choices: str = "",
    material_ids: list[uuid.UUID] | None = None,
    force_new: bool = False,
    follow_up: bool = False,
) -> Message:
    """One turn: the teacher's message in, the agent's reply and at most one card out.
    `choices` is the quick choices' sentence, sent beside their words: it is kept under them in
    the record, read by the agent, and taken literally for the rules. `force_new` makes any
    brief in the reply a new lesson; `follow_up` says the teacher pressed the button to follow
    up a shared difficulty."""
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    # The record shows their words and, under them, the settings they pressed. Both are read
    # for an instruction, a rule or a lesson's name.
    text = "\n\n".join(part for part in (text, choices) if part)
    await store.add_message(
        db,
        conversation,
        role=MessageRole.TEACHER,
        text=text,
        data={"choices": choices} if choices else {},
        material_ids=[str(m) for m in material_ids or []],
    )
    focus = await focus_of(db, conversation, teacher)
    # A lesson they name by title is the one shown to the agent, even in a fresh conversation.
    named = await _named(db, teacher, text)
    if named is not None and (focus.lesson is None or named.plan_id != focus.lesson.plan_id):
        focus = Focus(named, None)
    # The fixed prompt as it stands when the turn is made, not when the server started: the
    # test set is also run with a module of it left out (bench.teacher_set).
    fixed = SYSTEM
    system, manifest = await _system(db, teacher, focus, fixed)
    block, manifest["stands"] = _stands(focus, follow_up=follow_up)
    system += "\n" + block
    asks_new = bool(_ASKS_NEW.search(text)) and not is_empty_draft(focus.lesson)
    # The check below reads their lessons, which it cannot load itself.
    theirs = await latest_versions(db, teacher)

    def follows_the_facts(value: TeacherTurnOut) -> None:
        reason = _lacks(value, focus, theirs, follow_up=follow_up, asks_new=asks_new)
        if reason:
            raise SendBackOnce(reason)

    materials = await materials_of(db, focus.lesson.plan_id) if focus.lesson else []
    history = await _history(db, conversation, materials)
    manifest["message_count"] = len(history)
    request = {"text": text, "material_ids": [str(m) for m in material_ids or []]}

    try:
        out, result, tries = await ask_structured(
            client,
            TeacherTurnServing,
            purpose="teacher_thread",
            system=system,
            messages=history,
            max_tokens=6000,
            check=follows_the_facts,
            # The fixed prompt is the same every turn: read from the cache within minutes.
            cache_prefix=fixed,
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
                version=PROMPT_VERSION,
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
        version=PROMPT_VERSION,
        session_id=focus.session.id if focus.session else None,
    )
    db.add(turn)
    await db.flush()

    # The model cannot decide to act: only what this message asked for, as an instruction in
    # the teacher's own words, is done.
    ordered = asked_for(text)
    asked = [a for a in dict.fromkeys(out.do) if a in ordered]
    conflicts: list[str] = []
    # Nor may it reach a student the teacher did not name: the prompt holds students' own
    # words, and a guide the model volunteers is not the teacher's.
    if out.guide and out.guide.student_ref.strip().lower() not in unquoted(text).lower():
        out.guide = None
        conflicts.append(ConflictCode.FALSE_CLAIM.value)
    guided = out.guide.student_ref.lower() if out.guide else None
    claimed = [
        sentence
        for sentence in supervisor.claims_teacher_action(out.reply)
        # A sentence stands only if it names an action and every action it claims was asked
        # for; "approving it and starting it" goes when only the approval was, and so does a
        # claim that names no asked action at all ("I've sent the outcomes").
        if not ((named := {a for a in _SAID if _SAID[a].search(sentence)}) and named <= set(asked))
        # Passing the teacher's words on to that student is the agent's to do.
        and not (guided and guided in sentence.lower())
    ]
    # Starting and ending are buttons: any sentence claiming to do either is struck.
    claimed += [
        sentence.strip()
        for sentence in _SENTENCES.split(out.reply)
        if sentence.strip() and sentence.strip() not in claimed and claims_a_button_action(sentence)
    ]
    if claimed:
        # Asked in words to start or end: say where the button is, whatever card is in focus.
        own = unquoted(text)
        buttons = [a for a in ("run", "end") if _SAID[a].search(own)]
        hint = (
            "Starting and ending are buttons: Start with a class is on the lesson card, "
            "End the lesson is on the class card."
            if buttons
            else _next_button(focus)
        )
        out.reply = supervisor.without_claims(out.reply, claimed, hint)
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

    force_new = force_new or asks_new
    changed = await _apply_brief(
        db, teacher, out, focus, said=text, choices=choices, force_new=force_new
    )
    if changed is None and out.guess_answer:
        _answered_in_words(focus.lesson, out.guess_answer, text)
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
