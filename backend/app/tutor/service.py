"""The per-turn pipeline (concept note S3).

    authorise -> record -> grade -> retrieve evidence -> choose permitted rung
    -> generate -> validate -> supervise -> persist -> route attention -> reply

Two invariants hold whatever happens in the middle:

* the student always gets a civil reply - a provider failure is withheld help,
  never a 500 and never a stack trace;
* the student never receives more help than the teacher's contract permits,
  and that is decided after generation, not asked for before it.
"""

import json
import time
import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import (
    EXCEPTION_PRIORITY,
    ConflictCode,
    EvidenceKind,
    ExceptionKind,
    ExceptionStatus,
    LeakageCheck,
    Rung,
    ValidationOutcome,
)
from app.events import broker
from app.grading import ExactMatchGrader, Grader
from app.ledger import append, attempt_count, attempt_payload, incorrect_count
from app.models import ContractItem, Exception_, LessonContract, Session, TutorTurn, User
from app.schemas import AttemptResult, TutorResponse
from app.tutor.memory import EvidenceCard, LedgerMemoryProvider, MemoryProvider
from app.tutor.policy import AssistanceLadder, LadderPolicy, PolicyInput, TutorPolicy
from app.tutor.providers import (
    LLMProvider,
    ProviderTimeout,
    TutorRequest,
    get_provider,
)
from app.tutor.supervisor import PolicySupervisor, Supervisor, SupervisorAction

PROMPT_VERSION = "tutor-prompt-v1"

# What a student sees when help could not be produced safely. It says the truth
# without blaming them and without leaking why.
WITHHELD_MESSAGE = (
    "I can't give you a useful hint for this one. Your teacher has been told."
)
CORRECT_MESSAGE = "That's correct."


@dataclass
class TutorService:
    """The four replaceable modules the note asks for, in one place."""

    memory: MemoryProvider
    policy: TutorPolicy
    supervisor: Supervisor
    provider: LLMProvider
    grader: Grader

    @classmethod
    def default(cls) -> "TutorService":
        return cls(
            memory=LedgerMemoryProvider(),
            policy=LadderPolicy(),
            supervisor=PolicySupervisor(),
            provider=get_provider(get_settings().llm_provider),
            grader=ExactMatchGrader(),
        )

    async def handle_attempt(
        self,
        db: AsyncSession,
        *,
        session: Session,
        contract: LessonContract,
        student: User,
        item: ContractItem,
        answer: str,
    ) -> AttemptResult:
        thresholds = contract.exception_thresholds or {}
        vocabulary = tuple(m["code"] for m in (item.misconception_vocabulary or []))

        # 1. Record the attempt. Grading decides correctness before any model runs.
        grade = self.grader.grade(answer, item.expected_answer)
        index = await attempt_count(db, student.id, item.id) + 1
        attempt = await append(
            db,
            session_id=session.id,
            student_id=student.id,
            item_id=item.id,
            objective_id=item.objective_id,
            kind=EvidenceKind.ATTEMPT,
            correct=grade.correct,
            attempt_index=index,
            payload=attempt_payload(answer, grade),
            provenance={"source": "student"},
        )

        # 2. Retrieve this student's own evidence, then choose the permitted rung.
        card = await self.memory.card(
            db,
            student.id,
            item.objective_id,
            min_occurrences=int(thresholds.get("repeated_misconception", 2)),
        )
        wrong_so_far = await incorrect_count(db, student.id, item.id)
        decision = self.policy.decide(
            PolicyInput(
                ladder=AssistanceLadder.from_contract(contract.assistance_ladder),
                incorrect_attempts=wrong_so_far,
                correct=grade.correct,
                recurring_misconception=card.recurring.code if card.recurring else None,
            )
        )

        # 3. Generate, validate and supervise.
        turn = await self._tutor_turn(
            db,
            session=session,
            student=student,
            item=item,
            attempt_id=attempt.id,
            permitted=decision.rung,
            target=decision.target_misconception,
            policy_version=decision.policy_version,
            vocabulary=vocabulary,
            card=card,
            answer=answer,
        )
        response, conflicts = turn

        # 4. Route the teacher's attention.
        raised = await self._raise_exceptions(
            db,
            session=session,
            student=student,
            item=item,
            attempt_id=attempt.id,
            correct=grade.correct,
            wrong_so_far=wrong_so_far,
            response=response,
            conflicts=conflicts,
            card=card,
            thresholds=thresholds,
        )

        await db.commit()

        if grade.correct:
            message = CORRECT_MESSAGE
        elif response is None:
            message = WITHHELD_MESSAGE
        else:
            message = response.message

        return AttemptResult(
            attempt_id=attempt.id,
            correct=grade.correct,
            attempt_index=index,
            tutor_message=message,
            help_given=response is not None and not grade.correct,
            teacher_notified=bool(raised),
        )

    async def _tutor_turn(
        self,
        db: AsyncSession,
        *,
        session: Session,
        student: User,
        item: ContractItem,
        attempt_id: uuid.UUID,
        permitted: Rung,
        target: str | None,
        policy_version: str,
        vocabulary: tuple[str, ...],
        card: EvidenceCard,
        answer: str,
    ) -> tuple[TutorResponse | None, tuple[ConflictCode, ...]]:
        """One model call, validated and supervised, with at most one retry.

        Returns the response the student may receive, or None if help was
        withheld. Either way a `TutorTurn` row is written: a withheld turn is
        evidence about the platform, and S5 counts them.
        """
        request = TutorRequest(
            item_prompt=item.prompt,
            student_answer=answer,
            rung=permitted,
            hint_template=(item.hint_templates or {}).get(permitted.value),
            misconception_vocabulary=vocabulary,
            target_misconception=target,
            evidence_summary=card.summary_text(),
        )

        started = time.perf_counter()
        response: TutorResponse | None = None
        conflicts: tuple[ConflictCode, ...] = ()
        outcome = ValidationOutcome.OK
        raw = ""

        for attempt_number in range(2):
            is_retry = attempt_number == 1
            try:
                raw = await self.provider.generate(request)
                candidate = TutorResponse.model_validate_json(
                    raw, context={"misconception_vocabulary": vocabulary}
                )
            except (ValidationError, ValueError, json.JSONDecodeError):
                conflicts = (ConflictCode.MALFORMED_OUTPUT,)
                outcome = (
                    ValidationOutcome.WITHHELD if is_retry else ValidationOutcome.REGENERATED
                )
                if is_retry:
                    break
                continue
            except ProviderTimeout:
                conflicts = ()
                outcome = ValidationOutcome.WITHHELD
                raw = ""
                break

            verdict = self.supervisor.review(
                candidate,
                permitted=permitted,
                expected_answer=item.expected_answer,
                vocabulary=vocabulary,
                is_retry=is_retry,
            )
            if verdict.accepted:
                response = candidate
                outcome = ValidationOutcome.REGENERATED if is_retry else ValidationOutcome.OK
                conflicts = ()
                break

            conflicts = verdict.conflicts
            if verdict.action is SupervisorAction.WITHHOLD:
                outcome = ValidationOutcome.WITHHELD
                break
            outcome = ValidationOutcome.REGENERATED

        if response is None:
            outcome = ValidationOutcome.WITHHELD

        db.add(
            TutorTurn(
                session_id=session.id,
                student_id=student.id,
                item_id=item.id,
                attempt_record_id=attempt_id,
                rung_permitted=permitted.value,
                rung_used=response.rung_used.value if response else None,
                misconception_code=response.misconception_code if response else None,
                confidence=response.confidence if response else None,
                policy_version=policy_version,
                prompt_version=PROMPT_VERSION,
                provider=self.provider.name,
                model=self.provider.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                validation_outcome=outcome.value,
                leakage_check=(
                    LeakageCheck.FAILED.value
                    if ConflictCode.ANSWER_LEAKAGE in conflicts
                    else LeakageCheck.PASSED.value
                    if response
                    else LeakageCheck.SKIPPED.value
                ),
                conflicts=[c.value for c in conflicts],
                request={
                    "rung": permitted.value,
                    "target_misconception": target,
                    "evidence_lines": len(card.lines),
                },
                response={"raw": raw[:4000]},
            )
        )

        if response is not None and permitted is not Rung.ATTEMPT:
            await append(
                db,
                session_id=session.id,
                student_id=student.id,
                item_id=item.id,
                objective_id=item.objective_id,
                kind=EvidenceKind.HINT,
                payload={
                    "rung": response.rung_used.value,
                    "misconception_code": response.misconception_code,
                    "message": response.message,
                },
                provenance={
                    "source": "model",
                    "provider": self.provider.name,
                    "model": self.provider.model,
                    "policy_version": policy_version,
                    "prompt_version": PROMPT_VERSION,
                },
            )

        return response, conflicts

    @staticmethod
    async def _already_open(
        db: AsyncSession,
        session_id: uuid.UUID,
        student_id: uuid.UUID,
        item_id: uuid.UUID,
        kind: ExceptionKind,
    ) -> bool:
        return (
            await db.scalar(
                select(Exception_.id).where(
                    Exception_.session_id == session_id,
                    Exception_.student_id == student_id,
                    Exception_.item_id == item_id,
                    Exception_.kind == kind.value,
                    Exception_.status == ExceptionStatus.OPEN.value,
                )
            )
        ) is not None

    async def _raise_exceptions(
        self,
        db: AsyncSession,
        *,
        session: Session,
        student: User,
        item: ContractItem,
        attempt_id: uuid.UUID,
        correct: bool,
        wrong_so_far: int,
        response: TutorResponse | None,
        conflicts: tuple[ConflictCode, ...],
        card: EvidenceCard,
        thresholds: dict,
    ) -> list[Exception_]:
        raised: list[Exception_] = []

        def raise_(kind: ExceptionKind, summary: str, support: list, payload: dict) -> None:
            exc = Exception_(
                session_id=session.id,
                student_id=student.id,
                item_id=item.id,
                kind=kind.value,
                priority=EXCEPTION_PRIORITY[kind],
                summary=summary,
                supporting_record_ids=[str(r) for r in support],
                payload=payload,
            )
            db.add(exc)
            raised.append(exc)

        if response is not None and response.requests_teacher:
            raise_(
                ExceptionKind.TEACHER_REQUESTED,
                f"{student.pseudonym} asked for you.",
                [attempt_id],
                {},
            )

        repeated = int(thresholds.get("repeated_incorrect", 3))
        # `wrong_so_far` already counts the attempt just recorded. One live
        # exception per student and item: the console stays quiet, and a
        # resolved concern can legitimately come back.
        if not correct and wrong_so_far >= repeated and not await self._already_open(
            db, session.id, student.id, item.id, ExceptionKind.REPEATED_INCORRECT
        ):
            support = [attempt_id]
            summary = (
                f"{student.pseudonym} has {wrong_so_far} incorrect attempts "
                f"on item {item.ordinal}."
            )
            if card.recurring:
                support = [*card.recurring.supporting_record_ids, attempt_id]
                summary += (
                    f" Recurring: {card.recurring.code} "
                    f"(confidence {card.recurring.confidence})."
                )
            raise_(
                ExceptionKind.REPEATED_INCORRECT,
                summary,
                support,
                {
                    "attempts": wrong_so_far,
                    "recurring_misconception": card.recurring.code if card.recurring else None,
                    "confidence": card.recurring.confidence if card.recurring else None,
                },
            )

        if conflicts:
            raise_(
                ExceptionKind.ASSISTANCE_POLICY_CONFLICT,
                "The tutor produced a response outside the assistance policy; "
                "it was not shown to the student.",
                [attempt_id],
                {"conflicts": [c.value for c in conflicts]},
            )

        floor = float(thresholds.get("confidence_floor", 0.0))
        if response is not None and not correct and response.confidence < floor:
            raise_(
                ExceptionKind.TUTOR_UNCERTAINTY,
                f"The tutor is unsure how to help {student.pseudonym} "
                f"(confidence {response.confidence}).",
                [attempt_id],
                {"confidence": response.confidence},
            )

        for exc in raised:
            await broker.publish(
                session.id,
                {
                    "type": "exception",
                    "kind": exc.kind,
                    "priority": exc.priority,
                    "student": student.pseudonym,
                    "summary": exc.summary,
                },
            )
        return raised


def get_tutor_service() -> TutorService:
    """FastAPI dependency, and the injection point for tests that need a
    particular provider or an evidence-free memory."""
    return TutorService.default()
