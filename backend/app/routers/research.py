"""The researcher's view: counts, the records as CSV, and the agent's instructions.
Opened with a key from the environment; without one, none of it exists."""

import io
import secrets
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app import research
from app.agent import classroom, context, thread
from app.auth import DbSession
from app.config import get_settings

router = APIRouter(prefix="/api/research", tags=["research"])


def _researcher(x_research_key: str = Header(default="")) -> None:
    key = get_settings().research_key
    if not key or not secrets.compare_digest(key.encode(), x_research_key.encode()):
        raise HTTPException(status_code=404)


@router.get("/summary", dependencies=[Depends(_researcher)])
async def summary(db: DbSession) -> dict:
    return await research.summary(db)


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
    """The fixed instructions the agent works under, as they are in the code."""
    return {
        "teacher": thread.SYSTEM,
        "student": context.STUDENT_SYSTEM,
        "review": classroom.REVIEW_SYSTEM,
    }
