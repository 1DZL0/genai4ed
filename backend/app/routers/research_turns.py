"""Every model call, one at a time, for the researcher: what was said to the agent, what it
was shown, what it replied, and what the server made of it. Behind the same key as the
rest of the research view."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.agent.llm import parse_json
from app.auth import DbSession
from app.models import AgentTurn, Conversation, LessonContract, Session, User
from app.routers.research import _researcher

router = APIRouter(prefix="/api/research", tags=["research"])


def _reply(response: dict):
    """The model's reply as it sent it: parsed when it is JSON, else the raw text."""
    raw = response.get("raw", "")
    try:
        # The same reading the server used, so a reply in a code fence is still read.
        return parse_json(raw)
    except (TypeError, ValueError):
        return raw or response


@router.get("/turns", dependencies=[Depends(_researcher)])
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
    query = (
        query.where(AgentTurn.session_id == session_id)
        if session_id
        else query.where(AgentTurn.mode == "teacher")
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
