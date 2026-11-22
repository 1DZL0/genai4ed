"""The researcher's view: counts, the records as CSV, the agent's instructions, and every
model call one at a time (what was said to the agent, what it was shown, what it replied,
what the server made of it).
Who sees what: only the key from the environment opens it, and then it shows every teacher's
lessons. It is for the researchers, so a teacher is refused it as a student is; teachers read
their own students on the class board. The memory settings live here too, and those are a
signed-in teacher's own."""

import io
import secrets
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select

from app import research, research_view
from app.agent import approaches, classroom, context, memory_settings, thread
from app.agent.llm import parse_json
from app.auth import DbSession, get_current_user
from app.config import get_settings
from app.enums import Role
from app.models import AgentTurn, Conversation, LessonContract, Session, User

router = APIRouter(prefix="/api/research", tags=["research"])


async def _researcher(x_research_key: str = Header(default="")) -> None:
    """The key, or nothing: without it the research view does not exist."""
    key = get_settings().research_key
    if not (
        key and x_research_key and secrets.compare_digest(key.encode(), x_research_key.encode())
    ):
        raise HTTPException(status_code=404)


Reader = Depends(_researcher)


async def _teacher(request: Request, db: DbSession) -> User:
    """Memory settings are a signed-in teacher's own, so the key alone has none to read or
    change, and a student has none."""
    try:
        user = await get_current_user(request, db)
    except HTTPException:
        raise HTTPException(status_code=404) from None
    if user.role != Role.TEACHER.value:
        raise HTTPException(status_code=404)
    return user


Teacher = Depends(_teacher)


@router.get("/summary", dependencies=[Reader])
async def summary(db: DbSession) -> dict:
    """The whole study: totals, the conditions side by side, every lesson as a row."""
    return await research_view.overview(db)


@router.get("/lessons/{session_id}", dependencies=[Reader])
async def lesson(session_id: uuid.UUID, db: DbSession) -> dict:
    """One lesson run: every student as a row, the alerts, what the checks caught."""
    found = await research_view.lesson(db, session_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such lesson.")
    return found


@router.get("/lessons/{session_id}/students/{student_id}", dependencies=[Reader])
async def conversation(session_id: uuid.UUID, student_id: uuid.UUID, db: DbSession) -> dict:
    """One student's conversation in that lesson, with what each agent turn did."""
    found = await research_view.conversation(db, session_id, student_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such conversation.")
    return found


async def _memory(db: DbSession, teacher: User) -> dict:
    """The teacher's memory settings, and how many of their students have something
    remembered about them."""
    settings = await memory_settings.of(db, teacher.id)
    return {
        "settings": settings.model_dump(),
        "students": await memory_settings.remembered(db, teacher.id),
    }


@router.get("/memory")
async def memory(db: DbSession, teacher: User = Teacher) -> dict:
    """What the teacher has set about memory between their lessons."""
    return await _memory(db, teacher)


@router.put("/memory")
async def set_memory(
    settings: memory_settings.Settings, db: DbSession, teacher: User = Teacher
) -> dict:
    """The teacher's memory settings, all of them at once. They hold from each student's next
    turn in any lesson of this teacher's."""
    await memory_settings.save(db, teacher.id, settings)
    await db.commit()
    return await _memory(db, teacher)


@router.delete("/memory")
async def delete_memory(db: DbSession, teacher: User = Teacher) -> dict:
    """Deletes what is remembered of the teacher's students. Their lessons stay in the record,
    but nothing from before now is counted or recalled again."""
    await memory_settings.clear(db, teacher.id)
    await db.commit()
    return await _memory(db, teacher)


@router.get("/export", dependencies=[Reader])
async def export(db: DbSession, with_text: bool = False) -> Response:
    """The records as a zip of CSV files; `with_text` adds what was written."""
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        await research.export(db, out, with_text=with_text)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(out.glob("*.csv")):
                archive.write(file, file.name)
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="pact-export.zip"'},
    )


@router.get("/instructions", dependencies=[Reader])
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


@router.get("/turns", dependencies=[Reader])
async def turns(
    db: DbSession,
    session_id: uuid.UUID | None = None,
    limit: int = Query(300, ge=1, le=1000),
) -> dict:
    """The turns of one lesson run, or with no session the teachers' own conversations: the
    newest `limit` of them, oldest first, so new turns are never the ones cut off."""
    if session_id and await db.get(Session, session_id) is None:
        raise HTTPException(status_code=404, detail="No such lesson.")
    query = select(AgentTurn).order_by(AgentTurn.created_at.desc()).limit(limit)
    if session_id:
        query = query.where(AgentTurn.session_id == session_id)
    else:
        query = query.where(AgentTurn.mode == "teacher")
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
