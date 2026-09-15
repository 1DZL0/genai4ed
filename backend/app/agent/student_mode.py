"""The class agent teaching one student.

One turn: the student says something (or opens the lesson), the agent reads the
situation and decides what to do next, the server checks the reply against the
teacher's rules, and what happened is recorded - the judgment, where the
student now is, anything worth noticing - before the student sees the reply.

The agent proposes; the server disposes. It can suggest moving a student on,
but the step only changes if the move is accompanied by a judgment, and a reply
that gives away more than the rules allow never reaches the student.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import store, supervisor, triage
from app.agent.brief import LessonBrief
from app.agent.context import student_context
from app.agent.llm import LLMClient, LLMError, ask_structured, get_llm_client
from app.agent.supervisor import SupervisorAction
from app.enums import (
    EXCEPTION_PRIORITY,
    AgentMove,
    Audience,
    Disclosure,
    EvidenceKind,
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
    signals: list[SignalOut] = Field(default_factory=list, max_length=6)


class AgentUnavailable(Exception):
    """The model couldn't produce a reply. The student's message is kept."""


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

        screened: list[str] = []
        if text is not None:
            said = text.strip() or INTENTS.get(intent or "", "")
            await store.add_message(
                db,
                conversation,
                role=MessageRole.STUDENT,
                text=said,
                data={"intent": intent} if intent else {},
            )
            screened = supervisor.screen_student_message(said)
        if state.status == LearningStatus.NOT_STARTED.value:
            state.status = LearningStatus.IN_PROGRESS.value
        state.last_activity_at = now

        ctx = await student_context(
            db,
            session=session,
            contract=contract,
            student=student,
            conversation=conversation,
            state=state,
            intent=INTENTS.get(intent or ""),
        )
        step = brief.steps[state.step_index] if state.step_index < len(brief.steps) else None

        turn_out: StudentTurnOut | None = None
        verdict = supervisor.Verdict(SupervisorAction.ACCEPT)
        outcome = ValidationOutcome.OK
        result = None
        latency = 0
        conversation_msgs = ctx.messages
        for attempt in (1, 2):
            try:
                candidate, result, tries = await ask_structured(
                    self.client,
                    StudentTurnOut,
                    purpose="student_turn",
                    system=ctx.system,
                    messages=conversation_msgs,
                    max_tokens=900,
                )
            except LLMError as exc:
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
                message=candidate.message,
                move=candidate.move,
                disclosure=candidate.disclosure,
                judgment=candidate.assessment.judgment if candidate.assessment else None,
                step=step,
                rules=brief.rules,
                attempts_on_step=state.attempts_on_step + (1 if candidate.student_attempted else 0),
                is_retry=attempt == 2,
            )
            if verdict.accepted:
                turn_out = candidate
                break
            outcome = (
                ValidationOutcome.WITHHELD
                if verdict.action is SupervisorAction.WITHHOLD
                else ValidationOutcome.REGENERATED
            )
            conversation_msgs = [
                *ctx.messages,
                {"role": "assistant", "content": candidate.message},
                {
                    "role": "user",
                    "content": (
                        "(Platform check, not the student: that reply broke the teacher's rules - "
                        f"{verdict.reason}. Write a new reply that keeps to them.)"
                    ),
                },
            ]
            turn_out = candidate  # kept for the record; not shown

        withheld = not verdict.accepted
        turn = AgentTurn(
            session_id=session.id,
            student_id=student.id,
            conversation_id=conversation.id,
            mode="student",
            context_manifest=ctx.manifest,
            policy_version=POLICY_VERSION,
            prompt_version=PROMPT_VERSION,
            provider=result.provider if result else self.client.name,
            model=result.model if result else self.client.model,
            latency_ms=latency,
            validation_outcome=outcome.value if not withheld else ValidationOutcome.WITHHELD.value,
            leakage_check=(
                LeakageCheck.FAILED.value
                if withheld and "answer_leakage" in [c.value for c in verdict.conflicts]
                else LeakageCheck.PASSED.value
            ),
            conflicts=[c.value for c in verdict.conflicts],
            request={"text": text, "intent": intent, "step_index": state.step_index},
            response={"raw": (result.raw if result else "")[:6000]},
        )
        db.add(turn)
        await db.flush()

        topics = brief.topics
        base = {"topics": topics, "turn_id": str(turn.id)}
        alerts: list[Exception_] = []

        if withheld:
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
                text=f"A reply was held back: {verdict.reason}.",
                data={"conflicts": [c.value for c in verdict.conflicts]},
                turn_id=turn.id,
            )
            await append(
                db,
                session_id=session.id,
                student_id=student.id,
                kind=EvidenceKind.POLICY_EVENT,
                payload={
                    **base,
                    "conflicts": [c.value for c in verdict.conflicts],
                    "reason": verdict.reason,
                    "step_index": state.step_index,
                },
                provenance={"source": "supervisor", "policy_version": POLICY_VERSION},
            )
            # Their answer still counts, or a student could be kept waiting for help forever.
            if turn_out is not None and turn_out.student_attempted:
                state.attempts_on_step += 1
            signals: list[SignalOut] = []
        else:
            assert turn_out is not None
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
                    note="Asked the agent to drop its rules or hand over the work.",
                )
            )
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
        if 0 <= index < len(steps) and out.task:
            steps[index] = {**steps[index], "task": out.task}

        if out.student_attempted:
            state.attempts_on_step += 1
            if 0 <= index < len(steps):
                steps[index] = {**steps[index], "attempts": steps[index].get("attempts", 0) + 1}

        if out.assessment is not None:
            judgment = out.assessment.judgment
            if 0 <= index < len(steps):
                steps[index] = {**steps[index], "judgment": judgment.value}
            if judgment in (Judgment.NOT_MET, Judgment.UNCLEAR) and out.student_attempted:
                state.struggle_turns += 1
            elif judgment is Judgment.MET:
                state.struggle_turns = 0
            step = brief.steps[index] if 0 <= index < len(brief.steps) else None
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

        moved_from = index
        if out.move is AgentMove.ADVANCE and out.assessment is not None:
            if index + 1 < len(brief.steps):
                state.step_index = index + 1
            else:
                state.status = LearningStatus.COMPLETED.value
                state.completed_at = datetime.now(UTC)
        elif out.move is AgentMove.COMPLETE and out.assessment is not None:
            state.status = LearningStatus.COMPLETED.value
            state.completed_at = datetime.now(UTC)
        elif out.move is AgentMove.REVISIT and index > 0:
            state.step_index = index - 1

        if state.step_index != moved_from:
            state.attempts_on_step = 0
            state.struggle_turns = 0
        if state.step_index != moved_from or state.status == LearningStatus.COMPLETED.value:
            await append(
                db,
                session_id=session.id,
                student_id=student.id,
                kind=EvidenceKind.STEP_CHANGE,
                payload={
                    **base,
                    "from": moved_from,
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
        if signal.kind is SignalKind.MISCONCEPTION and action is not TriageAction.ALERT:
            students = await _students_with_misconception(db, session.id)
            if not triage.is_class_pattern(students):
                return None
            action = TriageAction.ALERT
            summary = f"{students} students show a similar misconception, most recently: {summary}"
        if action is not TriageAction.ALERT:
            return None

        already = await db.scalar(
            select(Exception_.id).where(
                Exception_.session_id == session.id,
                Exception_.student_id == student.id,
                Exception_.kind == kind.value,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
        if already is not None:
            return None
        alert = Exception_(
            session_id=session.id,
            student_id=student.id,
            kind=kind.value,
            priority=EXCEPTION_PRIORITY[kind],
            summary=summary,
            supporting_record_ids=[str(record.id)],
            payload={"signal": signal.kind.value, "seen": seen, "step_index": state.step_index},
        )
        db.add(alert)
        await db.flush()
        return alert


async def _students_with_misconception(db: AsyncSession, session_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(func.distinct(EvidenceRecord.student_id))).where(
                EvidenceRecord.session_id == session_id,
                EvidenceRecord.kind == EvidenceKind.SIGNAL.value,
                EvidenceRecord.payload["signal"].as_string() == SignalKind.MISCONCEPTION.value,
            )
        )
        or 0
    )
