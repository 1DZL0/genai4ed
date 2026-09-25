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
from app.agent import store, supervisor, triage
from app.agent.brief import LessonBrief
from app.agent.context import student_context
from app.agent.llm import LLMClient, LLMError, ask_structured, get_llm_client
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
    User,
)

POLICY_VERSION = "class-agent-v1"
PROMPT_VERSION = "student-turn-v1"

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
    judgment: Judgment
    criterion: str = Field(default="", max_length=300)
    evidence_quote: str = Field(default="", max_length=600)
    misconception: str | None = Field(default=None, max_length=300)


class SignalOut(BaseModel):
    kind: SignalKind
    severity: Severity = Severity.LOW
    note: str = Field(default="", max_length=400)


class StudentTurnOut(BaseModel):
    message: str = Field(min_length=1, max_length=2500)
    move: AgentMove
    student_attempted: bool = False
    assessment: AssessmentOut | None = None
    disclosure: Disclosure = Disclosure.NONE
    task: str | None = Field(default=None, max_length=1200)
    # True when this reply moves the student to the next step (or finishes the lesson).
    step_done: bool = False
    # Which rung of the help ladder the reply is, when the lesson runs on one.
    rung: str | None = Field(default=None, max_length=40)
    signals: list[SignalOut] = Field(default_factory=list, max_length=6)

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
    ) -> TurnResult:
        brief = LessonBrief.model_validate(contract.brief or {})
        conversation = await store.student_conversation(
            db, session_id=session.id, student_id=student.id
        )
        state = await learning_state(
            db, session_id=session.id, student_id=student.id, steps=len(brief.steps)
        )
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
                    max_tokens=900,
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
                        prompt_version=PROMPT_VERSION,
                        provider=self.client.name,
                        model=self.client.model,
                        latency_ms=0,
                        validation_outcome=ValidationOutcome.WITHHELD.value,
                        leakage_check=LeakageCheck.SKIPPED.value,
                        conflicts=["malformed_output"],
                        request={"text": text, "intent": intent},
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
                worked_example=intent == "example",
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
        turn = AgentTurn(
            session_id=session.id,
            student_id=student.id,
            conversation_id=conversation.id,
            mode="student",
            context_manifest=ctx.manifest,
            policy_version=POLICY_VERSION,
            prompt_version=PROMPT_VERSION,
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
            request={"text": text, "intent": intent, "step_index": state.step_index},
            response={"raw": result.raw[:6000]},
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
                    )
                )
            elif quote not in noticed.note:
                noticed.note = f"{noticed.note.rstrip('.')}. {quote}"[:400]
        if state.struggle_turns >= 3 and not any(s.kind is SignalKind.STRUGGLING for s in signals):
            signals.append(
                SignalOut(
                    kind=SignalKind.STRUGGLING,
                    severity=Severity.MEDIUM,
                    note=f"Not getting there on step {state.step_index + 1} after "
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

    async def _apply(self, db, *, session, student, brief, state, out: StudentTurnOut, base):
        """Move the student through the activity as far as the server accepts."""
        steps = list(state.steps or [])
        while len(steps) < len(brief.steps):
            steps.append({"judgment": None, "attempts": 0, "task": None})
        index = state.step_index
        was_completed = state.status == LearningStatus.COMPLETED.value
        last = index + 1 >= len(brief.steps)

        if out.student_attempted:
            state.attempts_on_step += 1
            if index < len(steps):
                steps[index] = {**steps[index], "attempts": steps[index].get("attempts", 0) + 1}

        judgment = out.assessment.judgment if out.assessment else None
        if out.assessment is not None:
            if index < len(steps):
                already = steps[index].get("judgment")
                steps[index] = {
                    **steps[index],
                    "judgment": (already if already == Judgment.MET.value else judgment.value),
                }
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
                },
                provenance={"source": "agent", "policy_version": POLICY_VERSION},
            )
            if out.assessment.misconception and not any(
                s.kind is SignalKind.MISCONCEPTION for s in out.signals
            ):
                out.signals.append(
                    SignalOut(kind=SignalKind.MISCONCEPTION, note=out.assessment.misconception)
                )

        # A move needs a judgment; met on the last step is the end.
        advancing = out.step_done or out.move in (AgentMove.ADVANCE, AgentMove.COMPLETE)
        if judgment is not None and (advancing or (judgment is Judgment.MET and last)):
            if last or out.move is AgentMove.COMPLETE:
                state.status = LearningStatus.COMPLETED.value
                state.completed_at = datetime.now(UTC)
            else:
                state.step_index = index + 1
        elif out.move is AgentMove.REVISIT and index > 0:
            state.step_index = index - 1

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
                    "move": out.move.value,
                    "completed": state.status == LearningStatus.COMPLETED.value,
                },
                provenance={"source": "agent", "policy_version": POLICY_VERSION},
            )
        state.steps = steps

    async def _record_signal(
        self, db, *, session, student, brief, state, signal: SignalOut, base
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
        action = triage.triage(signal.kind, severity=signal.severity, seen=seen, rules=brief.rules)
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
                "step_index": state.step_index,
            },
            provenance={"source": "agent", "policy_version": POLICY_VERSION},
        )

        kind = triage.ALERT_KIND[signal.kind]
        summary = signal.note or signal.kind.value.replace("_", " ")
        payload = {"signal": signal.kind.value, "seen": seen, "step_index": state.step_index}
        if signal.kind is SignalKind.MISCONCEPTION and action is not TriageAction.ALERT:
            # Several students wrong on the same step is one alert for the class.
            who = await _students_with_misconception(db, session.id, state.step_index)
            if not triage.is_class_pattern(len(who)):
                return None
            action = TriageAction.ALERT
            step = brief.steps[state.step_index] if state.step_index < len(brief.steps) else None
            where = f" on “{step.name}”" if step else ""
            summary = f"{len(who)} students show a misconception{where}, most recently: {summary}"
            payload["students"] = who
        if action is not TriageAction.ALERT:
            return None

        # One open alert of a kind per student (per step, for a class pattern).
        already = select(Exception_.id).where(
            Exception_.session_id == session.id,
            Exception_.kind == kind.value,
            Exception_.status == ExceptionStatus.OPEN.value,
        )
        if kind is ExceptionKind.MISCONCEPTION_PATTERN:
            already = already.where(
                Exception_.payload["step_index"].as_integer() == state.step_index
            )
        else:
            already = already.where(Exception_.student_id == student.id)
        if await db.scalar(already) is not None:
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
