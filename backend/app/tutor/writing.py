"""Written responses: help while writing, and a score the teacher confirms.

The same guarantees as short answers, adapted to work with no single right
answer (concept note S2; Scenario 1):

* The tutor asks for an attempt first. "I'm stuck" with nothing new written
  gets "have a go first", and help climbs one step only after the student has
  written something since the last help.
* Help fades: once a student writes a good deal on their own, the next help is
  a step lower, not higher.
* Help never passes the teacher's limit, and a reply long enough to be the
  student's paragraph is held back - checked on the reply, not asked for in a
  prompt, because a model told not to write the answer sometimes does anyway.
* A rubric score is only ever a suggestion. It is stored as suggested; the
  student sees nothing until the teacher confirms it.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import (
    EXCEPTION_PRIORITY,
    LADDER,
    ConflictCode,
    EvidenceKind,
    ExceptionKind,
    ExceptionStatus,
    LeakageCheck,
    Rung,
    ScoreStatus,
    TutorAsk,
    ValidationOutcome,
    rung_index,
)
from app.events import broker
from app.ledger import append
from app.models import (
    ContractItem,
    EvidenceRecord,
    Exception_,
    LessonContract,
    RubricScore,
    Session,
    TutorTurn,
    User,
)
from app.tutor.providers import (
    LLMProvider,
    ProviderTimeout,
    ScoreRequest,
    WritingRequest,
    get_provider,
)

POLICY_VERSION = "writing-ladder-v1"
PROMPT_VERSION = "writing-prompt-v1"
SCORE_PROMPT_VERSION = "rubric-score-v1"

WITHHELD_MESSAGE = "I can't help with that one right now. Your teacher has been told."

# Writing this many words on your own since the last help counts as getting
# going, so the next help steps down rather than up.
FADE_AFTER_WORDS = 25
# Language help may rewrite a single sentence only after this many earlier
# language questions on the same task (the scenario: "after failed attempts").
REWRITE_AFTER_LANGUAGE_ASKS = 2

# The most a reply may say at each step. A model paragraph is roughly 60-100
# words, so anything near that is the work, not help with it.
WORD_LIMIT = {
    Rung.ATTEMPT: 40,
    Rung.DIAGNOSTIC_QUESTION: 45,
    Rung.CONCEPTUAL_CUE: 45,
    Rung.TARGETED_HINT: 50,
    Rung.ANALOGOUS_EXAMPLE: 60,
    Rung.PARTIAL_STEP: 70,
    Rung.FULL_SOLUTION: 400,
}
ASK_WORD_LIMIT = {TutorAsk.LANGUAGE: 70, TutorAsk.FEEDBACK: 90, TutorAsk.QUESTION: 60}
SENTENCE_LIMIT = {Rung.PARTIAL_STEP: 3, Rung.FULL_SOLUTION: 20}
DEFAULT_SENTENCE_LIMIT = 2
ASK_SENTENCE_LIMIT = {TutorAsk.LANGUAGE: 4, TutorAsk.FEEDBACK: 5, TutorAsk.QUESTION: 3}


# ---------- structured output ----------


class WritingResponse(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    rung_used: Rung
    rewrites_sentence: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    requests_teacher: bool = False


class CriterionScore(BaseModel):
    name: str
    points: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=600)


class ScoreResponse(BaseModel):
    criteria: list[CriterionScore]
    keep: str = ""
    develop: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    def check_against(self, rubric: list[dict]) -> None:
        """Every criterion scored once, and never above its maximum."""
        maxima = {c["name"]: int(c["max"]) for c in rubric}
        names = [c.name for c in self.criteria]
        if sorted(names) != sorted(maxima):
            raise ValueError(f"scored {names}, rubric has {sorted(maxima)}")
        for c in self.criteria:
            if c.points > maxima[c.name]:
                raise ValueError(f"{c.name}: {c.points} is more than {maxima[c.name]}")


# ---------- policy ----------


def _words(text: str) -> int:
    return len(text.split())


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


@dataclass(frozen=True)
class HelpDecision:
    rung: Rung
    level: int  # 0 = have a go first
    no_progress: bool
    no_progress_streak: int
    may_rewrite_sentence: bool


def decide_help(
    *, ask: TutorAsk, words_now: int, history: list[dict], max_rung: Rung, allow_full: bool
) -> HelpDecision:
    """The next permitted step, from this student's own requests on this task.

    Pure: no I/O, so the rules above are tested directly.
    """
    ceiling = rung_index(max_rung)
    if not allow_full:
        ceiling = min(ceiling, rung_index(Rung.PARTIAL_STEP))

    stuck = [h for h in history if h["ask"] == TutorAsk.STUCK.value]
    level = stuck[-1]["level"] if stuck else 0
    words_before = stuck[-1]["words"] if stuck else 0
    streak = 0
    for h in reversed(stuck):
        if not h["no_progress"]:
            break
        streak += 1

    language_asks = sum(1 for h in history if h["ask"] == TutorAsk.LANGUAGE.value)
    may_rewrite = language_asks >= REWRITE_AFTER_LANGUAGE_ASKS

    if ask is TutorAsk.STUCK:
        if words_now == 0 or (stuck and words_now <= words_before):
            return HelpDecision(Rung.ATTEMPT, 0, True, streak + 1, may_rewrite)
        if words_now - words_before >= FADE_AFTER_WORDS and level > 1:
            level -= 1  # getting going: step down
        else:
            level += 1
        level = max(1, min(level, ceiling))
        return HelpDecision(LADDER[level], level, False, 0, may_rewrite)

    # Language help, feedback and questions do not climb the ladder; they are
    # held to the current step, at least a question back.
    level = max(1, min(level, ceiling))
    return HelpDecision(LADDER[level], level, False, streak, may_rewrite)


# ---------- supervisor ----------


def review_writing(
    response: WritingResponse, *, ask: TutorAsk, permitted: Rung, may_rewrite: bool
) -> tuple[ConflictCode, ...]:
    conflicts: list[ConflictCode] = []
    if rung_index(response.rung_used) > rung_index(permitted):
        conflicts.append(ConflictCode.RUNG_EXCEEDED)

    if ask is TutorAsk.STUCK:
        word_limit = WORD_LIMIT[permitted]
        sentence_limit = SENTENCE_LIMIT.get(permitted, DEFAULT_SENTENCE_LIMIT)
    else:
        word_limit = ASK_WORD_LIMIT[ask]
        sentence_limit = ASK_SENTENCE_LIMIT[ask]
    if _words(response.message) > word_limit or _sentences(response.message) > sentence_limit:
        conflicts.append(ConflictCode.WROTE_THE_WORK)

    if response.rewrites_sentence and not (ask is TutorAsk.LANGUAGE and may_rewrite):
        conflicts.append(ConflictCode.EARLY_REWRITE)
    return tuple(conflicts)


# ---------- service ----------


class WritingError(Exception):
    """Something the student can be told plainly (a 409 or 422)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class HelpReply:
    message: str
    withheld: bool
    teacher_notified: bool


@dataclass
class WritingService:
    provider: LLMProvider

    # ----- state read from the ledger -----

    async def _records(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        student_id: uuid.UUID,
        item_id: uuid.UUID,
        kind: EvidenceKind,
    ) -> list[EvidenceRecord]:
        return list(
            (
                await db.scalars(
                    select(EvidenceRecord)
                    .where(
                        EvidenceRecord.session_id == session_id,
                        EvidenceRecord.student_id == student_id,
                        EvidenceRecord.item_id == item_id,
                        EvidenceRecord.kind == kind.value,
                    )
                    .order_by(EvidenceRecord.created_at)
                )
            ).all()
        )

    async def submission(self, db, session_id, student_id, item_id) -> EvidenceRecord | None:
        found = await self._records(db, session_id, student_id, item_id, EvidenceKind.SUBMISSION)
        return found[-1] if found else None

    async def latest_text(self, db, session_id, student_id, item_id) -> str:
        submitted = await self.submission(db, session_id, student_id, item_id)
        if submitted is not None:
            return str(submitted.payload.get("text", ""))
        drafts = await self._records(db, session_id, student_id, item_id, EvidenceKind.DRAFT)
        return str(drafts[-1].payload.get("text", "")) if drafts else ""

    # ----- actions -----

    async def save_draft(
        self, db: AsyncSession, *, session: Session, student: User, item: ContractItem, text: str
    ) -> None:
        if await self.submission(db, session.id, student.id, item.id) is not None:
            raise WritingError(409, "You've already submitted this. Your teacher has it.")
        if text == await self.latest_text(db, session.id, student.id, item.id):
            return  # nothing new; autosave calls this often
        await append(
            db,
            session_id=session.id,
            student_id=student.id,
            item_id=item.id,
            objective_id=item.objective_id,
            kind=EvidenceKind.DRAFT,
            payload={"text": text, "words": _words(text)},
            provenance={"source": "student"},
        )
        await db.commit()

    async def ask(
        self,
        db: AsyncSession,
        *,
        session: Session,
        contract: LessonContract,
        student: User,
        item: ContractItem,
        ask: TutorAsk,
        text: str,
        question: str = "",
    ) -> HelpReply:
        if await self.submission(db, session.id, student.id, item.id) is not None:
            raise WritingError(409, "You've already submitted this task.")
        if ask is TutorAsk.QUESTION and not question.strip():
            raise WritingError(422, "Type your question for the tutor.")
        await self.save_draft(db, session=session, student=student, item=item, text=text)

        history = [
            r.payload
            for r in await self._records(
                db, session.id, student.id, item.id, EvidenceKind.TUTOR_REQUEST
            )
        ]
        ladder = contract.assistance_ladder or {}
        decision = decide_help(
            ask=ask,
            words_now=_words(text),
            history=history,
            max_rung=Rung(ladder.get("max_rung", Rung.PARTIAL_STEP.value)),
            allow_full=bool(ladder.get("allow_full_solution")),
        )
        request_record = await append(
            db,
            session_id=session.id,
            student_id=student.id,
            item_id=item.id,
            objective_id=item.objective_id,
            kind=EvidenceKind.TUTOR_REQUEST,
            payload={
                "ask": ask.value,
                "question": question,
                "words": _words(text),
                "level": decision.level,
                "rung_permitted": decision.rung.value,
                "no_progress": decision.no_progress,
            },
            provenance={"source": "student"},
        )

        request = WritingRequest(
            task=item.prompt,
            student_text=text,
            ask=ask.value,
            question=question,
            rung=decision.rung,
            hint_template=(item.hint_templates or {}).get(decision.rung.value),
            material_notes=(contract.material or {}).get("notes", ""),
            may_rewrite_sentence=decision.may_rewrite_sentence,
        )
        response, conflicts, outcome, raw, latency = await self._generate(request, decision, ask)

        db.add(
            TutorTurn(
                session_id=session.id,
                student_id=student.id,
                item_id=item.id,
                attempt_record_id=request_record.id,
                rung_permitted=decision.rung.value,
                rung_used=response.rung_used.value if response else None,
                misconception_code=None,
                confidence=response.confidence if response else None,
                policy_version=POLICY_VERSION,
                prompt_version=PROMPT_VERSION,
                provider=self.provider.name,
                model=self.provider.model,
                latency_ms=latency,
                validation_outcome=outcome.value,
                leakage_check=(
                    LeakageCheck.FAILED.value
                    if ConflictCode.WROTE_THE_WORK in conflicts
                    else LeakageCheck.PASSED.value
                    if response
                    else LeakageCheck.SKIPPED.value
                ),
                conflicts=[c.value for c in conflicts],
                request={"ask": ask.value, "rung": decision.rung.value, "words": _words(text)},
                response={"raw": raw[:4000]},
            )
        )
        if response is not None:
            await append(
                db,
                session_id=session.id,
                student_id=student.id,
                item_id=item.id,
                objective_id=item.objective_id,
                kind=EvidenceKind.HINT,
                payload={
                    "rung": response.rung_used.value,
                    "ask": ask.value,
                    "message": response.message,
                },
                provenance={
                    "source": "model",
                    "provider": self.provider.name,
                    "model": self.provider.model,
                    "policy_version": POLICY_VERSION,
                    "prompt_version": PROMPT_VERSION,
                },
            )

        raised = await self._route_attention(
            db,
            session=session,
            contract=contract,
            student=student,
            item=item,
            request_id=request_record.id,
            decision=decision,
            response=response,
            conflicts=conflicts,
        )
        await db.commit()
        for exc in raised:
            await broker.publish(
                session.id,
                {
                    "type": "exception",
                    "kind": exc.kind,
                    "student": student.pseudonym,
                    "summary": exc.summary,
                },
            )
        return HelpReply(
            message=response.message if response else WITHHELD_MESSAGE,
            withheld=response is None,
            teacher_notified=bool(raised),
        )

    async def _generate(self, request, decision: HelpDecision, ask: TutorAsk):
        started = time.perf_counter()
        response: WritingResponse | None = None
        conflicts: tuple[ConflictCode, ...] = ()
        outcome = ValidationOutcome.OK
        raw = ""
        for attempt_number in range(2):
            is_retry = attempt_number == 1
            try:
                raw = await self.provider.generate_writing(request)
                candidate = WritingResponse.model_validate_json(raw)
            except (ValidationError, ValueError, json.JSONDecodeError):
                conflicts = (ConflictCode.MALFORMED_OUTPUT,)
                outcome = ValidationOutcome.WITHHELD if is_retry else ValidationOutcome.REGENERATED
                continue
            except ProviderTimeout:
                conflicts, outcome, raw = (), ValidationOutcome.WITHHELD, ""
                break
            found = review_writing(
                candidate,
                ask=ask,
                permitted=decision.rung,
                may_rewrite=decision.may_rewrite_sentence,
            )
            if not found:
                response = candidate
                conflicts = ()
                outcome = ValidationOutcome.REGENERATED if is_retry else ValidationOutcome.OK
                break
            conflicts = found
            outcome = ValidationOutcome.REGENERATED
        if response is None:
            outcome = ValidationOutcome.WITHHELD
        return response, conflicts, outcome, raw, int((time.perf_counter() - started) * 1000)

    async def _route_attention(
        self, db, *, session, contract, student, item, request_id, decision, response, conflicts
    ) -> list[Exception_]:
        thresholds = contract.exception_thresholds or {}
        raised: list[Exception_] = []

        async def already_open(kind: ExceptionKind) -> bool:
            return (
                await db.scalar(
                    select(Exception_.id).where(
                        Exception_.session_id == session.id,
                        Exception_.student_id == student.id,
                        Exception_.item_id == item.id,
                        Exception_.kind == kind.value,
                        Exception_.status == ExceptionStatus.OPEN.value,
                    )
                )
                is not None
            )

        def add(kind: ExceptionKind, summary: str, payload: dict) -> None:
            exc = Exception_(
                session_id=session.id,
                student_id=student.id,
                item_id=item.id,
                kind=kind.value,
                priority=EXCEPTION_PRIORITY[kind],
                summary=summary,
                supporting_record_ids=[str(request_id)],
                payload=payload,
            )
            db.add(exc)
            raised.append(exc)

        limit = int(thresholds.get("repeated_incorrect", 3))
        if decision.no_progress_streak >= limit and not await already_open(ExceptionKind.STUCK):
            add(
                ExceptionKind.STUCK,
                f"Asked for help {decision.no_progress_streak} times on task {item.ordinal} "
                "without writing anything new.",
                {"streak": decision.no_progress_streak},
            )
        if conflicts and response is None:
            add(
                ExceptionKind.ASSISTANCE_POLICY_CONFLICT,
                f"On task {item.ordinal} the tutor wrote a reply that went past your limits, "
                "so it was not shown to the student.",
                {"conflicts": [c.value for c in conflicts]},
            )
        floor = float(thresholds.get("confidence_floor", 0.0))
        if response is not None and response.confidence < floor:
            add(
                ExceptionKind.TUTOR_UNCERTAINTY,
                f"The tutor wasn't sure how to help on task {item.ordinal}, "
                "so it is passing this to you.",
                {"confidence": response.confidence},
            )
        return raised

    async def submit(
        self, db: AsyncSession, *, session: Session, student: User, item: ContractItem, text: str
    ) -> RubricScore | None:
        """Hand the work in, and ask for a score suggestion for the teacher."""
        if not text.strip():
            raise WritingError(422, "Write something before you submit.")
        if await self.submission(db, session.id, student.id, item.id) is not None:
            raise WritingError(409, "You've already submitted this task.")
        record = await append(
            db,
            session_id=session.id,
            student_id=student.id,
            item_id=item.id,
            objective_id=item.objective_id,
            kind=EvidenceKind.SUBMISSION,
            payload={"text": text, "words": _words(text)},
            provenance={"source": "student"},
        )

        rubric = list((item.rubric or {}).get("criteria", []))
        parsed: ScoreResponse | None = None
        for _ in range(2):
            try:
                raw = await self.provider.score(
                    ScoreRequest(task=item.prompt, student_text=text, criteria=tuple(rubric))
                )
                candidate = ScoreResponse.model_validate_json(raw)
                candidate.check_against(rubric)
                parsed = candidate
                break
            except (ValidationError, ValueError, json.JSONDecodeError, ProviderTimeout):
                continue

        score = None
        if parsed is None:
            # No safe suggestion: the teacher marks it by hand, and is told.
            db.add(
                Exception_(
                    session_id=session.id,
                    student_id=student.id,
                    item_id=item.id,
                    kind=ExceptionKind.TUTOR_UNCERTAINTY.value,
                    priority=EXCEPTION_PRIORITY[ExceptionKind.TUTOR_UNCERTAINTY],
                    summary=(
                        f"Couldn't suggest a score for task {item.ordinal}. "
                        "Please mark it yourself."
                    ),
                    supporting_record_ids=[str(record.id)],
                    payload={},
                )
            )
        else:
            maxima = {c["name"]: int(c["max"]) for c in rubric}
            criteria = [
                {"name": c.name, "points": c.points, "max": maxima[c.name], "reason": c.reason}
                for c in parsed.criteria
            ]
            score = RubricScore(
                session_id=session.id,
                student_id=student.id,
                item_id=item.id,
                submission_record_id=record.id,
                status=ScoreStatus.SUGGESTED.value,
                suggested={"criteria": criteria, "keep": parsed.keep, "develop": parsed.develop},
                suggested_total=sum(c.points for c in parsed.criteria),
                provider=self.provider.name,
                model=self.provider.model,
                prompt_version=SCORE_PROMPT_VERSION,
            )
            db.add(score)
        await db.commit()
        return score


def get_writing_service() -> WritingService:
    """FastAPI dependency, and the injection point for tests that need a
    particular provider."""
    return WritingService(provider=get_provider(get_settings().llm_provider))


async def confirm_score(
    db: AsyncSession,
    score: RubricScore,
    *,
    teacher: User,
    rubric: list[dict],
    points: dict[str, int] | None,
    comment: str | None,
) -> RubricScore:
    """The teacher's decision. Their points replace the suggestion's where given."""
    maxima = {c["name"]: int(c["max"]) for c in rubric}
    chosen = []
    for c in score.suggested["criteria"]:
        value = (points or {}).get(c["name"], c["points"])
        if not 0 <= value <= maxima.get(c["name"], c["max"]):
            raise WritingError(
                422, f"{c['name']} must be between 0 and {maxima.get(c['name'], c['max'])}."
            )
        chosen.append({**c, "points": value})
    score.confirmed = {
        "criteria": chosen,
        "keep": score.suggested.get("keep", ""),
        "develop": score.suggested.get("develop", []),
    }
    score.confirmed_total = sum(c["points"] for c in chosen)
    score.comment = comment
    score.status = ScoreStatus.CONFIRMED.value
    score.confirmed_by = teacher.id
    score.confirmed_at = datetime.now(UTC)
    return score
