"""The class agent teaching one student: one turn in, one checked reply out.

The agent proposes a reply, judgment and move; the server checks the reply
against the teacher's rules, records what happened, then moves the student.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import study
from app.agent import approaches, scaffold, store, supervisor, triage
from app.agent.brief import LessonBrief
from app.agent.context import prompt_set, student_context
from app.agent.llm import (
    LLMClient,
    LLMError,
    LLMResult,
    ask_structured,
    bare_schema,
    get_llm_client,
)
from app.agent.supervisor import normalise
from app.config import get_settings
from app.enums import (
    EXCEPTION_PRIORITY,
    AgentMove,
    Audience,
    Disclosure,
    EvidenceKind,
    ExceptionKind,
    ExceptionStatus,
    Judgment,
    LeakageCheck,
    LearningStatus,
    MessageRole,
    Severity,
    SignalKind,
    TriageAction,
    ValidationOutcome,
)
from app.events import broker
from app.ledger import append
from app.models import (
    AgentTurn,
    EvidenceRecord,
    Exception_,
    LearningState,
    LessonContract,
    Message,
    Session,
    SessionParticipant,
    User,
)

POLICY_VERSION = "class-agent-v1"


def prompt_version() -> str:
    """The name of the prompt the tutor runs on now. The structured prompts are named by a
    hash of their wording, so an edit anywhere is a new version on every turn it shapes."""
    chosen = prompt_set()
    if chosen == "v8":
        return "student-turn-v8"
    return scaffold.version(
        depth=chosen == "v10", schema=bare_schema(StudentTurnOut.model_json_schema())
    )


HELD_BACK = (
    "Let's keep this one yours. Tell me what you think so far, even if you're not sure, "
    "and we'll build on it together."
)

INTENTS = {
    "dont_understand": "I don't understand.",
    "another_way": "Can you explain that another way?",
    "example": "Can you give me an example?",
    "why_wrong": "Why is my answer wrong?",
}


class AssessmentOut(BaseModel):
    """How the student's attempt measures against the step's success criteria."""

    judgment: Judgment = Field(
        description=(
            "met, partial, not_met or unclear, against the success criteria. Never call a "
            "partly wrong answer met."
        )
    )
    criterion: str = Field(
        default="", max_length=300, description="The criterion you judged against, in a few words."
    )
    evidence_quote: str = Field(
        default="", max_length=600, description="Their exact words that show it."
    )
    misconception: str | None = Field(
        default=None,
        max_length=300,
        description="Only when their words show a specific wrong idea; say it in plain words.",
    )
    depth_shown: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description=(
            "The depth in the student's own words on this step, 1 to 4, never counting "
            "anything you supplied: 1 recall or a bare answer; 2 a method applied or a concept "
            "explained; 3 a justification, a comparison or evidence; 4 sustained reasoning. "
            "The lower level when it could be read two ways."
        ),
    )
    uncertain: bool = Field(
        default=False, description="True when depth_shown could be read two ways."
    )


class SignalOut(BaseModel):
    """Something you noticed about the student, as an observation."""

    kind: SignalKind = Field(
        description=(
            "struggling, misconception, manipulation_attempt, off_task, fast_progress, "
            "unresolved_question, wellbeing (the student may be unsafe or distressed), or "
            "asked_for_teacher (they ask for their teacher in words)."
        )
    )
    severity: Severity = Field(default=Severity.LOW, description="low, medium or high.")
    note: str = Field(
        default="",
        max_length=400,
        description="What you saw, in plain words, with their words where they matter.",
    )
    tell_teacher: bool = Field(
        default=False,
        description=(
            "True when the teacher should know now, going by the list under Allowed right "
            "now. Wellbeing where the student may be unsafe is always high and always true. "
            "This is your only way to reach the teacher."
        ),
    )


class StudentTurnOut(BaseModel):
    """One reply to the student. They see only the message."""

    message: str = Field(
        min_length=1,
        max_length=2500,
        description="What the student reads, written as How to talk says.",
    )
    move: AgentMove = Field(
        description=(
            "What this reply does: ask, follow_up, clarify, challenge, hint, explain, example, "
            "simplify, harder, justify, revisit, advance, complete or decline. advance or "
            "complete only with a met assessment; complete only on the last step, because it "
            "ends the whole lesson; revisit only to send them back a step."
        )
    )
    student_attempted: bool = Field(
        default=False,
        description="True only when their message is an attempt at the current step.",
    )
    assessment: AssessmentOut | None = Field(
        default=None, description="When they attempted: the judgment, with their exact words."
    )
    disclosure: Disclosure = Field(
        default=Disclosure.NONE,
        description=(
            "Honestly, how much of this step's answer your reply gives away: none, hint, "
            "partial or full. A worked example of a similar problem, or one step of this one "
            "done for them, counts as partial; the full answer or a complete solution counts "
            "as full."
        ),
    )
    task: str | None = Field(
        default=None,
        max_length=1200,
        description=(
            "The question your message actually asked, so it stays on screen; on a reply that "
            "moves them on, the next step's first question. Null when you asked nothing, and "
            "the last one stays on screen."
        ),
    )
    step_done: bool = Field(
        default=False,
        description=(
            "True only with a met assessment, when you are moving them to the next step and "
            "asking its first question in this same reply; the platform moves them when you "
            "set it. A step with several questions is done when each has been asked and met. "
            "On the last step a met answer ends the lesson whatever you set, so close it in "
            "that same reply."
        ),
    )
    rung: str | None = Field(
        default=None,
        max_length=40,
        description="On a help ladder, the rung this reply is; otherwise null.",
    )
    signals: list[SignalOut] = Field(
        default_factory=list,
        max_length=6,
        description="What you noticed, as observations; empty when nothing stood out.",
    )

    @field_validator("rung", mode="before")
    @classmethod
    def _known_rung(cls, value):
        return value if value in study.LADDER else None


class AgentUnavailable(Exception):
    """The model produced no reply; the student's message was not kept."""


@dataclass(frozen=True)
class TurnResult:
    reply: Message
    withheld: bool
    alerts: list[Exception_]


async def learning_state(
    db: AsyncSession, *, session_id: uuid.UUID, student_id: uuid.UUID, steps: int
) -> LearningState:
    state = await db.scalar(
        select(LearningState).where(
            LearningState.session_id == session_id, LearningState.student_id == student_id
        )
    )
    if state is None:
        state = LearningState(
            session_id=session_id,
            student_id=student_id,
            status=LearningStatus.NOT_STARTED.value,
            step_index=0,
            attempts_on_step=0,
            struggle_turns=0,
            turns=0,
            steps=[{"judgment": None, "attempts": 0, "task": None} for _ in range(steps)],
        )
        db.add(state)
        await db.flush()
    return state


class StudentAgent:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()

    async def respond(
        self,
        db: AsyncSession,
        *,
        session: Session,
        contract: LessonContract,
        student: User,
        text: str | None,
        intent: str | None = None,
        guidance: str | None = None,
    ) -> TurnResult:
        """The agent's reply to what the student said; with `text` None, its opening line,
        or with `guidance` its reply to what the teacher just asked for this student."""
        brief = LessonBrief.model_validate(contract.brief or {})
        if guidance:
            # The teacher can go past their own rules for this one reply: the answer, or a skip.
            brief.rules = brief.rules.model_copy(update={"full_answer_after_attempts": 0})
        conversation = await store.student_conversation(
            db, session_id=session.id, student_id=student.id
        )
        state = await learning_state(
            db, session_id=session.id, student_id=student.id, steps=len(brief.steps)
        )
        # What the student says in this turn is about the step they are on now, even if the
        # turn moves them on.
        turn_step = state.step_index
        now = datetime.now(UTC)

        # A help button alone sends the button's words; nothing in that turn is judged.
        help_only = bool(intent) and not (text or "").strip()
        screened: list[str] = []
        said = ""
        stored = None
        if text is not None:
            said = text.strip() or INTENTS.get(intent or "", "")
            stored = await store.add_message(
                db,
                conversation,
                role=MessageRole.STUDENT,
                text=said,
                data={"intent": intent} if intent else {},
            )
            screened = supervisor.screen_student_message(said)
        finished_before = state.status == LearningStatus.COMPLETED.value
        if state.status == LearningStatus.NOT_STARTED.value:
            state.status = LearningStatus.IN_PROGRESS.value
        state.last_activity_at = now

        cond = await study.condition(db, session_id=session.id, student_id=student.id)
        on_ladder = cond.get("policy") == "ladder" if cond else brief.rules.ladder
        # With enforcement off (simulations) every check still runs and is recorded.
        enforce = cond.get("supervisor", get_settings().supervisor_enforce)
        answering = text is not None and not help_only
        attempts_now = state.attempts_on_step + (1 if answering else 0)
        permitted = (
            study.permitted_rung(
                attempts_now,
                full_allowed=brief.rules.allowed_disclosure(attempts_now) is Disclosure.FULL,
            )
            if on_ladder and text is not None  # the opening greeting is not help
            else None
        )

        ctx = await student_context(
            db,
            session=session,
            contract=contract,
            student=student,
            conversation=conversation,
            state=state,
            intent=INTENTS.get(intent or ""),
            condition=cond,
            rung=permitted,
            attempts=attempts_now,
            teacher_asks=guidance,
            # On a help ladder the ladder decides the help; the button is just asking.
            example_button=help_only and intent == "example" and not on_ladder,
        )
        step = brief.steps[state.step_index] if state.step_index < len(brief.steps) else None
        later = tuple(
            s.reference_answer
            for s in brief.steps[state.step_index + 1 :]
            if s.reference_answer and len(s.reference_answer.split()) >= 3
        )
        # Every conflict found, first draft included.
        found: list[str] = []
        outcome = ValidationOutcome.OK
        latency = 0
        conversation_msgs = ctx.messages
        for attempt in (1, 2):
            try:
                turn_out, result, tries = await ask_structured(
                    self.client,
                    StudentTurnOut,
                    purpose="student_turn",
                    system=ctx.system,
                    messages=conversation_msgs,
                    max_tokens=1800,
                )
            except LLMError as exc:
                if stored is not None:
                    await db.delete(stored)
                db.add(
                    AgentTurn(
                        session_id=session.id,
                        student_id=student.id,
                        conversation_id=conversation.id,
                        mode="student",
                        context_manifest=ctx.manifest,
                        policy_version=POLICY_VERSION,
                        prompt_version=prompt_version(),
                        provider=self.client.name,
                        model=self.client.model,
                        latency_ms=0,
                        validation_outcome=ValidationOutcome.WITHHELD.value,
                        leakage_check=LeakageCheck.SKIPPED.value,
                        conflicts=["malformed_output"],
                        request={"text": text, "intent": intent, "guidance": guidance},
                        response={"error": str(exc)[:500]},
                    )
                )
                await db.commit()
                raise AgentUnavailable(str(exc)) from exc
            latency += result.latency_ms
            if tries > 1:
                outcome = ValidationOutcome.REGENERATED
            verdict = supervisor.review(
                message=turn_out.message,
                move=turn_out.move,
                disclosure=turn_out.disclosure,
                judgment=turn_out.assessment.judgment if turn_out.assessment else None,
                step=step,
                rules=brief.rules,
                attempts_on_step=state.attempts_on_step + (1 if turn_out.student_attempted else 0),
                is_retry=attempt == 2,
                task=turn_out.task or "",
                later_references=later,
                rung=turn_out.rung,
                permitted_rung=permitted,
                # An answer the student already gave is theirs to hear back, not a leak.
                student_said="\n".join(
                    [m["content"] for m in ctx.messages if m["role"] == "user"] + [said]
                ),
                # The button promises an example of a different problem, never more help
                # than the lesson allows.
                worked_example=help_only and intent == "example" and not on_ladder,
                teacher_moved=bool(guidance),
            )
            found += [c.value for c in verdict.conflicts if c.value not in found]
            if verdict.accepted or not enforce:
                break
            outcome = ValidationOutcome.REGENERATED
            conversation_msgs = [
                *ctx.messages,
                {"role": "assistant", "content": turn_out.message},
                {
                    "role": "user",
                    "content": (
                        "(Platform check, not the student: that reply broke the teacher's rules - "
                        f"{verdict.reason}. Write a new reply that keeps to them.)"
                    ),
                },
            ]

        withheld = enforce and not verdict.accepted
        if withheld:
            outcome = ValidationOutcome.WITHHELD
        # What the reply did, counted: the cheap numbers behind "is the tutor good".
        classmates = (
            await db.scalars(
                select(User.pseudonym)
                .join(SessionParticipant, SessionParticipant.student_id == User.id)
                .where(SessionParticipant.session_id == session.id, User.id != student.id)
            )
        ).all()
        earlier = [m["content"] for m in ctx.messages if m["role"] == "assistant"]
        measured = supervisor.measures(
            message=turn_out.message,
            task=turn_out.task,
            previous=earlier[-1] if earlier else "",
            classmates=classmates,
            finished=finished_before or turn_out.move is AgentMove.COMPLETE,
            target_dok=step.depth if step and prompt_set() == "v10" else None,
            depth_shown=turn_out.assessment.depth_shown if turn_out.assessment else None,
            uncertain=bool(turn_out.assessment and turn_out.assessment.uncertain),
        )
        turn = AgentTurn(
            session_id=session.id,
            student_id=student.id,
            conversation_id=conversation.id,
            mode="student",
            context_manifest=ctx.manifest,
            policy_version=POLICY_VERSION,
            prompt_version=prompt_version(),
            provider=result.provider,
            model=result.model,
            latency_ms=latency,
            validation_outcome=outcome.value,
            leakage_check=(
                LeakageCheck.FAILED.value
                if "answer_leakage" in found
                else LeakageCheck.PASSED.value
            ),
            conflicts=found,
            request={
                "text": text,
                "intent": intent,
                "guidance": guidance,
                "step_index": state.step_index,
                "retry_reason": result.retry_reason,
            },
            response={"raw": result.raw[:6000], "measures": measured},
        )
        db.add(turn)
        await db.flush()

        base = {"topics": brief.topics, "turn_id": str(turn.id)}
        alerts: list[Exception_] = []

        if withheld:
            conflicts = [c.value for c in verdict.conflicts]
            reply = await store.add_message(
                db,
                conversation,
                role=MessageRole.AGENT,
                text=HELD_BACK,
                data={"move": AgentMove.DECLINE.value, "withheld": True},
                turn_id=turn.id,
            )
            await store.add_message(
                db,
                conversation,
                role=MessageRole.EVENT,
                audience=Audience.TEACHER,
                text="The agent's reply was held back and not shown to the student: "
                f"{verdict.reason}.",
                data={"conflicts": conflicts},
                turn_id=turn.id,
            )
            await append(
                db,
                session_id=session.id,
                student_id=student.id,
                kind=EvidenceKind.POLICY_EVENT,
                payload={
                    **base,
                    "conflicts": conflicts,
                    "reason": verdict.reason,
                    "step_index": state.step_index,
                },
                provenance={"source": "supervisor", "policy_version": POLICY_VERSION},
            )
            kind = ExceptionKind.POLICY_CONFLICT
            alert = Exception_(
                session_id=session.id,
                student_id=student.id,
                kind=kind.value,
                priority=EXCEPTION_PRIORITY[kind],
                summary="The agent's reply broke the rules on both drafts, so the student got a "
                f"holding line instead: {verdict.reason}.",
                supporting_record_ids=[],
                payload={"step_index": state.step_index},
            )
            db.add(alert)
            await db.flush()
            alerts.append(alert)
            # Their answer still counts, or a student could wait for help forever.
            if turn_out.student_attempted:
                state.attempts_on_step += 1
            signals: list[SignalOut] = []
        else:
            if help_only or finished_before:
                # A help button, or a finished lesson: talk, but judge and move nothing.
                turn_out.assessment = None
                turn_out.student_attempted = False
                turn_out.step_done = False
                turn_out.task = None
                if turn_out.move in (AgentMove.REVISIT, AgentMove.ADVANCE, AgentMove.COMPLETE):
                    turn_out.move = AgentMove.EXPLAIN if help_only else AgentMove.FOLLOW_UP
                if help_only:
                    state.struggle_turns += 1
            # The quote must be the student's own words.
            if turn_out.assessment is not None and said:
                quote = turn_out.assessment.evidence_quote.strip()
                if not quote or normalise(quote) not in normalise(said):
                    turn_out.assessment.evidence_quote = said[:600]
            await self._apply(
                db,
                session=session,
                student=student,
                brief=brief,
                state=state,
                out=turn_out,
                base=base,
                guided=bool(guidance),
            )
            signals = list(turn_out.signals)
            reply = await store.add_message(
                db,
                conversation,
                role=MessageRole.AGENT,
                text=turn_out.message,
                data={
                    "move": turn_out.move.value,
                    "disclosure": turn_out.disclosure.value,
                    "step_index": state.step_index,
                    "task": turn_out.task,
                    "assessment": turn_out.assessment.model_dump(mode="json")
                    if turn_out.assessment
                    else None,
                },
                turn_id=turn.id,
            )

        # What the server saw for itself, whether or not the agent reported it.
        if screened and not any(s.kind is SignalKind.MANIPULATION_ATTEMPT for s in signals):
            signals.append(
                SignalOut(
                    kind=SignalKind.MANIPULATION_ATTEMPT,
                    severity=Severity.MEDIUM,
                    note="Asked the agent for the answer, or to set its rules aside.",
                )
            )
        distress = supervisor.screen_wellbeing(said) if said and not help_only else None
        if distress:
            quote = f"Said “{said[:120]}”."
            noticed = next((s for s in signals if s.kind is SignalKind.WELLBEING), None)
            if noticed is None:
                signals.append(
                    SignalOut(
                        kind=SignalKind.WELLBEING,
                        severity=Severity.HIGH if distress == "high" else Severity.MEDIUM,
                        note=f"{quote} May be upset; worth a word.",
                        tell_teacher=distress == "high",
                    )
                )
            else:
                if quote not in noticed.note:
                    noticed.note = f"{noticed.note.rstrip('.')}. {quote}"[:400]
                if distress == "high":
                    noticed.tell_teacher = True
        if state.struggle_turns >= 3 and not any(s.kind is SignalKind.STRUGGLING for s in signals):
            signals.append(
                SignalOut(
                    kind=SignalKind.STRUGGLING,
                    severity=Severity.MEDIUM,
                    note=f"Not getting there on step {turn_step + 1} after "
                    f"{state.struggle_turns} tries.",
                )
            )

        for signal in signals:
            alert = await self._record_signal(
                db,
                session=session,
                student=student,
                brief=brief,
                state=state,
                signal=signal,
                base=base,
                step_index=turn_step,
            )
            if alert is not None:
                alerts.append(alert)

        state.turns += 1
        await db.commit()
        await broker.publish(
            session.id,
            {"type": "student_update", "student": student.pseudonym, "alerts": len(alerts)},
        )
        return TurnResult(reply=reply, withheld=withheld, alerts=alerts)

    async def _apply(
        self, db, *, session, student, brief, state, out: StudentTurnOut, base, guided=False
    ):
        """Move the student through the activity as far as the server accepts."""
        steps = list(state.steps or [])
        while len(steps) < len(brief.steps):
            steps.append({"judgment": None, "attempts": 0, "task": None})
        index = state.step_index
        was_completed = state.status == LearningStatus.COMPLETED.value
        last = index + 1 >= len(brief.steps)

        judgment = out.assessment.judgment if out.assessment else None
        if index < len(steps):
            given = {
                Disclosure.HINT: "hints",
                Disclosure.PARTIAL: "examples" if out.move is AgentMove.EXAMPLE else "worked",
            }.get(out.disclosure)
            if given:
                steps[index] = {**steps[index], given: steps[index].get(given, 0) + 1}
            steps[index].setdefault("since", datetime.now(UTC).isoformat())
            # A right answer below the step's target, not moved on: the tutor asked for the
            # why. Counted, so the scaffold can say when it has asked enough.
            judged = out.assessment
            if (
                judged is not None
                and judged.judgment is Judgment.MET
                and judged.depth_shown is not None
                and index < len(brief.steps)
                and judged.depth_shown < brief.steps[index].depth
                and not out.step_done
                and out.move not in (AgentMove.ADVANCE, AgentMove.COMPLETE)
            ):
                steps[index] = {
                    **steps[index],
                    "depth_asks": steps[index].get("depth_asks", 0) + 1,
                }
        if out.student_attempted:
            # "After two tries" means two that weren't right: a right line doesn't unlock help.
            if judgment is not Judgment.MET:
                state.attempts_on_step += 1
            if index < len(steps):
                steps[index] = {**steps[index], "attempts": steps[index].get("attempts", 0) + 1}

        if out.assessment is not None:
            if judgment in (Judgment.NOT_MET, Judgment.UNCLEAR):
                state.struggle_turns += 1
            elif judgment is Judgment.MET:
                state.struggle_turns = 0
            step = brief.steps[index] if index < len(brief.steps) else None
            await append(
                db,
                session_id=session.id,
                student_id=student.id,
                kind=EvidenceKind.ASSESSMENT,
                payload={
                    **base,
                    "step_index": index,
                    "step_name": step.name if step else "",
                    "judgment": judgment.value,
                    "criterion": out.assessment.criterion,
                    "evidence_quote": out.assessment.evidence_quote,
                    "misconception": out.assessment.misconception,
                    "depth_shown": out.assessment.depth_shown,
                    "depth_uncertain": out.assessment.uncertain,
                    "target_dok": step.depth if step else None,
                },
                provenance={"source": "agent", "policy_version": POLICY_VERSION},
            )
            if out.assessment.misconception and not any(
                s.kind is SignalKind.MISCONCEPTION for s in out.signals
            ):
                out.signals.append(
                    SignalOut(kind=SignalKind.MISCONCEPTION, note=out.assessment.misconception)
                )

        # A move needs a judgment, or the teacher saying so; met on the last step is the end.
        advancing = out.step_done or out.move in (AgentMove.ADVANCE, AgentMove.COMPLETE)
        if (judgment is Judgment.MET and (advancing or last)) or (guided and advancing):
            # Only the last step ends the lesson; "complete" earlier is one step on.
            if last:
                state.status = LearningStatus.COMPLETED.value
                state.completed_at = datetime.now(UTC)
            else:
                state.step_index = index + 1
        elif out.move is AgentMove.REVISIT and index > 0:
            state.step_index = index - 1

        # A step is met only when it is finished; a right line on an open step is part met.
        if judgment is not None and index < len(steps):
            finished = state.step_index > index or state.status == LearningStatus.COMPLETED.value
            already = steps[index].get("judgment")
            if already != Judgment.MET.value:
                shown = judgment
                if judgment is Judgment.MET and not finished:
                    shown = Judgment.PARTIAL
                steps[index] = {**steps[index], "judgment": shown.value}

        # The task belongs to the step the student is now on.
        if out.task and state.step_index < len(steps):
            steps[state.step_index] = {**steps[state.step_index], "task": out.task}

        completed_now = state.status == LearningStatus.COMPLETED.value and not was_completed
        if (
            completed_now
            and all(
                s.get("judgment") == Judgment.MET.value and s.get("attempts", 0) <= 1 for s in steps
            )
            and not any(s.kind is SignalKind.FAST_PROGRESS for s in out.signals)
        ):
            out.signals.append(
                SignalOut(
                    kind=SignalKind.FAST_PROGRESS, note="Met every step at the first attempt."
                )
            )
        if state.step_index != index:
            state.attempts_on_step = 0
            state.struggle_turns = 0
            if state.step_index < len(steps):
                steps[state.step_index] = {
                    **steps[state.step_index],
                    "since": datetime.now(UTC).isoformat(),
                }
        # An alert that time has answered. Moving on clears "struggling"; a right answer clears
        # "off task". The record keeps the alert, marked as cleared by what the student did next.
        if state.step_index > index or completed_now:
            await _let_go(
                db,
                session,
                student,
                ExceptionKind.STRUGGLING,
                # Only what they were stuck on before the step they are on now: after going back
                # a step, moving forward again must not clear the step they could not do.
                before_step=None if completed_now else state.step_index,
                because=(
                    "finished the activity"
                    if completed_now
                    else f"moved on to step {state.step_index + 1}"
                )
                + (" after the teacher's guidance" if guided else ""),
            )
        if judgment is Judgment.MET:
            await _let_go(
                db, session, student, ExceptionKind.OFF_TASK, because="back on task, answered right"
            )
        if state.step_index != index or completed_now:
            await append(
                db,
                session_id=session.id,
                student_id=student.id,
                kind=EvidenceKind.STEP_CHANGE,
                payload={
                    **base,
                    "from": index,
                    "to": state.step_index,
                    "step_name": (
                        brief.steps[state.step_index].name
                        if state.step_index < len(brief.steps)
                        else ""
                    ),
                    "move": out.move.value,
                    "completed": state.status == LearningStatus.COMPLETED.value,
                },
                provenance={"source": "agent", "policy_version": POLICY_VERSION},
            )
        state.steps = steps

    async def _record_signal(
        self, db, *, session, student, brief, state, signal: SignalOut, base, step_index
    ) -> Exception_ | None:
        """Log the signal, and open an alert when triage says the teacher should see it."""
        seen = (
            await db.scalar(
                select(func.count(EvidenceRecord.id)).where(
                    EvidenceRecord.session_id == session.id,
                    EvidenceRecord.student_id == student.id,
                    EvidenceRecord.kind == EvidenceKind.SIGNAL.value,
                    EvidenceRecord.payload["signal"].as_string() == signal.kind.value,
                )
            )
            or 0
        ) + 1
        action = triage.decide(
            signal.kind,
            tell_teacher=signal.tell_teacher,
            rule=brief.rules.escalation_for(signal.kind),
            seen=seen,
        )
        record = await append(
            db,
            session_id=session.id,
            student_id=student.id,
            kind=EvidenceKind.SIGNAL,
            payload={
                **base,
                "signal": signal.kind.value,
                "severity": signal.severity.value,
                "note": signal.note,
                "action": action.value,
                "step_index": step_index,
            },
            provenance={"source": "agent", "policy_version": POLICY_VERSION},
        )

        kind = triage.ALERT_KIND[signal.kind]
        summary = signal.note or signal.kind.value.replace("_", " ")
        payload = {"signal": signal.kind.value, "seen": seen, "step_index": step_index}
        pattern = False
        if signal.kind is SignalKind.MISCONCEPTION and action is not TriageAction.ALERT:
            # Several students wrong on the same step is one alert for the class.
            who = await _students_with_misconception(db, session.id, step_index)
            if not triage.is_class_pattern(len(who)):
                return None
            action = TriageAction.ALERT
            step = brief.steps[step_index] if step_index < len(brief.steps) else None
            where = f" on “{step.name}”" if step else ""
            summary = f"{len(who)} students show a misconception{where}, most recently: {summary}"
            payload["students"] = who
            pattern = True
        if action is not TriageAction.ALERT:
            return None

        # One open alert of a kind per student; a class pattern is one per step, whoever
        # tipped it. A misconception the teacher's rule (or the agent) raises for one student
        # is that student's, so another student's note never lands under their name.
        already = select(Exception_).where(
            Exception_.session_id == session.id,
            Exception_.kind == kind.value,
            Exception_.status == ExceptionStatus.OPEN.value,
        )
        if kind is ExceptionKind.MISCONCEPTION_PATTERN:
            already = already.where(Exception_.payload["step_index"].as_integer() == step_index)
            already = (
                already.where(Exception_.payload["students"].is_not(None))
                if pattern
                else already.where(
                    Exception_.student_id == student.id,
                    Exception_.payload["students"].is_(None),
                )
            )
        else:
            already = already.where(Exception_.student_id == student.id)
        open_one = await db.scalar(already)
        if open_one is not None:
            if kind in (ExceptionKind.SAFEGUARDING, ExceptionKind.TEACHER_REQUESTED):
                # What first made a student upset, or ask for help, stays in front; later notes
                # are added, never written over it.
                if summary not in open_one.summary:
                    open_one.summary = f"{open_one.summary.rstrip()} Later: {summary}"[:2000]
                open_one.payload = {**payload, **open_one.payload, "seen": seen}
            else:
                # The teacher reads the latest, not the first, of what keeps happening.
                open_one.summary = summary
                open_one.payload = {**open_one.payload, **payload}
            open_one.supporting_record_ids = [*open_one.supporting_record_ids, str(record.id)]
            return None
        alert = Exception_(
            session_id=session.id,
            student_id=student.id,
            kind=kind.value,
            priority=EXCEPTION_PRIORITY[kind],
            summary=summary,
            supporting_record_ids=[str(record.id)],
            payload=payload,
        )
        db.add(alert)
        await db.flush()
        return alert


async def _students_with_misconception(
    db: AsyncSession, session_id: uuid.UUID, step_index: int
) -> list[str]:
    """Pseudonyms of the students who have shown a misconception on this step."""
    rows = await db.execute(
        select(func.distinct(User.pseudonym))
        .select_from(EvidenceRecord)
        .join(User, User.id == EvidenceRecord.student_id)
        .where(
            EvidenceRecord.session_id == session_id,
            EvidenceRecord.kind == EvidenceKind.SIGNAL.value,
            EvidenceRecord.payload["signal"].as_string() == SignalKind.MISCONCEPTION.value,
            EvidenceRecord.payload["step_index"].as_integer() == step_index,
        )
        .order_by(User.pseudonym)
    )
    return [r[0] for r in rows]


async def _let_go(
    db, session, student, kind: ExceptionKind, *, because: str, before_step: int | None = None
) -> None:
    """Close an open alert of this kind for this student: what they did next answered it. The
    record keeps the alert, marked as cleared without the teacher, so the board can let it go
    and the research view can still count it. With `before_step`, only alerts about an
    earlier step (or about no step) go."""
    for alert in (
        await db.scalars(
            select(Exception_).where(
                Exception_.session_id == session.id,
                Exception_.student_id == student.id,
                Exception_.kind == kind.value,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
    ).all():
        about = alert.payload.get("step_index")
        if before_step is not None and isinstance(about, int) and about >= before_step:
            continue
        alert.status = ExceptionStatus.RESOLVED.value
        alert.payload = {
            **alert.payload,
            "cleared_because": because,
            "cleared_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }


async def preview_opening(
    client: LLMClient, *, brief: LessonBrief, approach: str | None = None
) -> tuple[StudentTurnOut, LLMResult]:
    """How step 1 would open for a student, from the brief as it stands. Nothing is saved to
    any student: it is for the teacher, to hear the tutor's voice before approving."""
    if not brief.steps:
        raise ValueError("The lesson has no steps yet.")
    chosen = prompt_set()
    system = scaffold.assemble(
        brief=brief,
        index=0,
        task=None,
        attempts=0,
        allowed=brief.rules.allowed_disclosure(0),
        guidance=[],
        noticed=scaffold.Noticed(
            planned_minutes=brief.duration_minutes, steps_after=len(brief.steps) - 1
        ),
        now="The student has just opened the lesson. Greet them and begin step 1.",
        depth=chosen != "v9",
    )
    if approach:
        system += "\n\n" + approaches.teaching(approach)
    out, result, _ = await ask_structured(
        client,
        StudentTurnOut,
        purpose="student_preview",
        system=system,
        messages=[{"role": "user", "content": "(The student is waiting for you.)"}],
        max_tokens=1800,
    )
    return out, result
