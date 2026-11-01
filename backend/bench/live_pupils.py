"""Named pupils in a running lesson, their words written by a model from a persona and a beat
plan, so a class on camera looks like a class. Used by tools/video/record.py for the pupils
off camera.

From backend/, with the containers up:

    uv run python -m bench.live_pupils --session <id> --teacher teacher-demo \
        --pupils 9P-05:steady,9P-07:anxious,9P-08:steady --turns 6 --pace 8
"""

import argparse
import asyncio
import uuid

import httpx
from sqlalchemy import select

from app.agent.brief import LessonBrief
from app.db import get_engine, get_sessionmaker
from app.models import LessonContract, Session
from bench.run_bench import API, BEATS, PUPIL_MODEL, PUPILS, Beat, Persona, PupilWriter, cheat_sheet

# A quiet pupil for the camera's class: short, hesitant, gets there; no stress line, no
# call for the teacher, so the only alert on the board is the one the story needs.
PUPILS["quiet"] = Persona(
    "quiet",
    "A quiet pupil who gives short, hesitant answers but gets there.",
    [Beat(k, BEATS[k]) for k in ("wrong", "right", "one_word", "right", "right", "how")],
)


async def brief_of(session_id: str) -> LessonBrief:
    async with get_sessionmaker()() as db:
        session = await db.get(Session, uuid.UUID(session_id))
        contract = await db.scalar(
            select(LessonContract).where(LessonContract.id == session.contract_id)
        )
        return LessonBrief.model_validate(contract.brief or {})


async def one(
    name: str, persona_name: str, teacher: str, session_id: str, writer, turns: int, pace: float
) -> None:
    persona = PUPILS[persona_name]
    c = httpx.AsyncClient(base_url=API, timeout=240)
    try:
        r = await c.post(
            "/api/auth/demo",
            json={"role": "student", "username": name, "password": "x", "teacher": teacher},
        )
        r.raise_for_status()
        await asyncio.sleep(pace / 2)
        view = (await c.post(f"/api/learn/{session_id}/start")).json()
        for beat in persona.plan[:turns]:
            if view.get("completed") or view.get("status") != "open":
                break
            await asyncio.sleep(pace)
            lines = [{"who": x["who"], "text": x["text"]} for x in view.get("lines", [])]
            if beat.kind.startswith("button:"):
                body = {"text": "", "intent": beat.kind.split(":", 1)[1]}
            elif beat.kind == "ask_teacher":
                view = (await c.post(f"/api/learn/{session_id}/request-teacher")).json()
                continue
            else:
                body = {"text": await writer.write(persona, beat, lines)}
            r = await c.post(f"/api/learn/{session_id}/messages", json=body)
            if r.status_code != 200:
                print(f"{name}: {r.status_code} {r.text[:100]}")
                await asyncio.sleep(10)
                continue
            view = r.json()
        print(f"{name} ({persona_name}): done")
    finally:
        await c.aclose()


async def main(a) -> None:
    writer = PupilWriter(PUPIL_MODEL, cheat_sheet(await brief_of(a.session)))
    pairs = [p.split(":") for p in a.pupils.split(",")]
    try:
        await asyncio.gather(
            *(
                one(name, persona, a.teacher, a.session, writer, a.turns, a.pace)
                for name, persona in pairs
            )
        )
    finally:
        await writer.client.aclose()
        await get_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--teacher", required=True)
    parser.add_argument("--pupils", required=True, help="name:persona, comma separated")
    parser.add_argument("--turns", type=int, default=6)
    parser.add_argument(
        "--pace", type=float, default=8.0, help="seconds a pupil takes between turns"
    )
    asyncio.run(main(parser.parse_args()))
