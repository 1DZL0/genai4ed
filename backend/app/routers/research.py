"""The researcher's view: counts, the records as CSV, and the agent's instructions.
Open to anyone signed in while the prototype is shown privately, or with the key from the
environment. ponytail: everyone signed in sees every lesson; narrow it before real students."""

import io
import secrets
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app import research, research_view
from app.agent import approaches, classroom, context, thread
from app.auth import DbSession, get_current_user
from app.config import get_settings

router = APIRouter(prefix="/api/research", tags=["research"])


async def _researcher(
    request: Request, db: DbSession, x_research_key: str = Header(default="")
) -> None:
    key = get_settings().research_key
    if key and x_research_key and secrets.compare_digest(key.encode(), x_research_key.encode()):
        return
    try:
        await get_current_user(request, db)
    except HTTPException:
        raise HTTPException(status_code=404) from None


@router.get("/summary", dependencies=[Depends(_researcher)])
async def summary(db: DbSession) -> dict:
    """The whole study: totals, the conditions side by side, every lesson as a row."""
    return await research_view.overview(db)


@router.get("/lessons/{session_id}", dependencies=[Depends(_researcher)])
async def lesson(session_id: uuid.UUID, db: DbSession) -> dict:
    """One lesson run: every student as a row, the alerts, what the checks caught."""
    found = await research_view.lesson(db, session_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such lesson.")
    return found


@router.get("/lessons/{session_id}/students/{student_id}", dependencies=[Depends(_researcher)])
async def conversation(session_id: uuid.UUID, student_id: uuid.UUID, db: DbSession) -> dict:
    """One student's conversation in that lesson, with what each agent turn did."""
    found = await research_view.conversation(db, session_id, student_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such conversation.")
    return found


@router.get("/export", dependencies=[Depends(_researcher)])
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
