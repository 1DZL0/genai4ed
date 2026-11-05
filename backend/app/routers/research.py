"""The researcher's view: counts, the records as CSV, the agent's instructions, and every
model call one at a time (what was said to the agent, what it was shown, what it replied,
what the server made of it).
Who sees what: the key from the environment opens every teacher's lessons; a signed-in
teacher sees only the runs of their own classes, and every conversation they open here is
written to the access log, as it is from the class board; a student never sees any of it."""

import io
import secrets
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select

from app import research, research_view
from app.agent import approaches, classroom, context, thread
from app.agent.llm import parse_json
from app.auth import DbSession, get_current_user
from app.config import get_settings
from app.enums import Role, TeacherAction
from app.models import AgentTurn, Conversation, LessonContract, Session, User
from app.routers.thread_common import log_access

router = APIRouter(prefix="/api/research", tags=["research"])


@dataclass(frozen=True)
class Scope:
    """Who is reading: a teacher, limited to their own classes, or nobody in particular,
    which is the researcher with the key and means everything."""

    teacher: User | None

    @property
    def teacher_id(self) -> uuid.UUID | None:
        return self.teacher.id if self.teacher else None


async def _researcher(
    request: Request, db: DbSession, x_research_key: str = Header(default="")
) -> Scope:
    key = get_settings().research_key
    if key and x_research_key and secrets.compare_digest(key.encode(), x_research_key.encode()):
        return Scope(teacher=None)
    try:
        user = await get_current_user(request, db)
    except HTTPException:
        raise HTTPException(status_code=404) from None
    # Students never: the view holds every student's words, marks and wellbeing notes.
    if user.role != Role.TEACHER.value:
        raise HTTPException(status_code=404)
    return Scope(teacher=user)


Reader = Depends(_researcher)


@router.get("/summary")
async def summary(db: DbSession, scope: Scope = Reader) -> dict:
    """The whole study: totals, the conditions side by side, every lesson as a row."""
    return await research_view.overview(db, teacher_id=scope.teacher_id)


@router.get("/lessons/{session_id}")
async def lesson(session_id: uuid.UUID, db: DbSession, scope: Scope = Reader) -> dict:
    """One lesson run: every student as a row, the alerts, what the checks caught."""
    found = await research_view.lesson(db, session_id, teacher_id=scope.teacher_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such lesson.")
    return found


@router.get("/lessons/{session_id}/students/{student_id}")
async def conversation(
    session_id: uuid.UUID, student_id: uuid.UUID, db: DbSession, scope: Scope = Reader
) -> dict:
    """One student's conversation in that lesson, with what each agent turn did. A teacher's
    read is logged like a read from the class board; the researcher's is not a teacher's."""
    found = await research_view.conversation(
        db, session_id, student_id, teacher_id=scope.teacher_id
    )
    if found is None:
        raise HTTPException(status_code=404, detail="No such conversation.")
    if scope.teacher is not None:
        log_access(
            db,
            scope.teacher,
            TeacherAction.TRANSCRIPT_DRILLDOWN,
            session_id=session_id,
            student_id=student_id,
            detail={"via": "research"},
        )
        await db.commit()
    return found


@router.get("/export")
async def export(db: DbSession, with_text: bool = False, scope: Scope = Reader) -> Response:
    """The records as a zip of CSV files; `with_text` adds what was written. A teacher's
    download holds their own classes only."""
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        await research.export(db, out, with_text=with_text, teacher_id=scope.teacher_id)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(out.glob("*.csv")):
                archive.write(file, file.name)
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="genai4ed-export.zip"'},
    )


@router.get("/instructions", dependencies=[Depends(_researcher)])
async def instructions() -> dict:
    """The fixed instructions the agent works under, as it is sent them."""
    return {
        "teacher": thread.SYSTEM,
        "student": context.STUDENT_SYSTEM,
        "review": classroom.REVIEW_SYSTEM,
        "approaches": approaches.for_research(),
    }


# ---------- every model call ----------


def _reply(response: dict):
    """The model's reply as it sent it: parsed when it is JSON, else the raw text."""
    raw = response.get("raw", "")
    try:
        # The same reading the server used, so a reply in a code fence is still read.
        return parse_json(raw)
    except (TypeError, ValueError):
        return raw or response


@router.get("/turns")
async def turns(
    db: DbSession,
    session_id: uuid.UUID | None = None,
    limit: int = Query(300, ge=1, le=1000),
    scope: Scope = Reader,
) -> dict:
    """The turns of one lesson run, or with no session the teachers' own conversations: the
    newest `limit` of them, oldest first, so new turns are never the ones cut off. A teacher
    gets their own runs and their own conversation with the agent."""
    if session_id:
        run = await db.get(Session, session_id)
        if run is None or not await research_view.owned(db, run, scope.teacher_id):
            raise HTTPException(status_code=404, detail="No such lesson.")
    query = select(AgentTurn).order_by(AgentTurn.created_at.desc()).limit(limit)
    if session_id:
        query = query.where(AgentTurn.session_id == session_id)
    else:
        query = query.where(AgentTurn.mode == "teacher")
        if scope.teacher is not None:
            query = query.join(Conversation, Conversation.id == AgentTurn.conversation_id).where(
                Conversation.teacher_id == scope.teacher.id
            )
    rows = list(reversed((await db.scalars(query)).all()))
    # A teacher's turns say whose conversation they come from.
    teachers = dict(
        (
            await db.execute(
                select(Conversation.id, User.pseudonym)
                .join(User, User.id == Conversation.teacher_id)
                .where(Conversation.id.in_({r.conversation_id for r in rows if r.conversation_id}))
            )
        ).all()
    )

    names = {
        u.id: u.pseudonym
        for u in (
            await db.scalars(select(User).where(User.id.in_({r.student_id for r in rows})))
        ).all()
    }
    title = None
    if session_id and (run := await db.get(Session, session_id)):
        contract = await db.get(LessonContract, run.contract_id)
        title = contract.title if contract else None

    return {
        "session_id": str(session_id) if session_id else None,
        "lesson": title,
        "turns": [
            {
                "id": str(r.id),
                "at": r.created_at.isoformat(),
                "mode": r.mode,
                "student": names.get(r.student_id),
                "teacher": teachers.get(r.conversation_id) if r.mode == "teacher" else None,
                "said": r.request.get("text"),
                "button": r.request.get("intent"),
                "error": r.request.get("error"),
                "retried_because": r.request.get("retry_reason"),
                "shown": r.context_manifest,
                "reply": _reply(r.response),
                "prompts": r.prompt_version,
                "model": r.model,
                "latency_ms": r.latency_ms,
                "outcome": r.validation_outcome,
                "leakage": r.leakage_check,
                "conflicts": r.conflicts,
            }
            for r in rows
        ],
    }
