"""Populate the development database with a realistic lesson, for looking at.

Drives the real pipeline through the real HTTP surface - no shortcuts - so what
lands in the tables is exactly what a lesson would produce:

* 10B-01 climbs the ladder on one item and trips the repeated-incorrect threshold
* 10B-02 gets an answer-leaking model, which the Supervisor withholds and logs
  as an assistance-policy conflict
* 10B-03 asks for the teacher directly
* the teacher then drills into a transcript, which the access log records

    uv run python -m app.seed --reset && uv run python -m app.demo
"""

import asyncio

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_engine, get_sessionmaker
from app.main import create_app
from app.models import ContractItem, LessonContract, Session, User
from app.tutor.providers import AnswerLeakingProvider
from app.tutor.service import TutorService, get_tutor_service


def headers(pseudonym: str) -> dict[str, str]:
    return {"X-GenAI4ED-Pseudonym": pseudonym}


async def main() -> None:
    async with get_sessionmaker()() as db:
        session = await db.scalar(select(Session))
        contract = await db.get(LessonContract, session.contract_id)
        items = (
            await db.scalars(
                select(ContractItem)
                .where(ContractItem.contract_id == contract.id)
                .order_by(ContractItem.ordinal)
            )
        ).all()
        students = {
            u.pseudonym: u
            for u in (await db.scalars(select(User).where(User.role == "student"))).all()
        }

    if session is None or not items:
        print("Nothing seeded. Run: uv run python -m app.seed --reset")
        return

    app = create_app()
    base = f"/api/sessions/{session.id}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://demo") as c:
        print("10B-01 works item 1, getting it wrong three times:")
        for answer in ("4", "6", "7"):
            r = await c.post(
                f"{base}/attempts",
                json={"item_id": str(items[0].id), "answer": answer},
                headers=headers("10B-01"),
            )
            body = r.json()
            print(f"  answered {answer!r} -> {body['tutor_message'][:64]}")
        print("  then gets item 2 right:")
        r = await c.post(
            f"{base}/attempts",
            json={"item_id": str(items[1].id), "answer": "5"},
            headers=headers("10B-01"),
        )
        print(f"  -> correct={r.json()['correct']}")

        print("10B-02 meets a model that tries to give the answer away:")
        leaking = TutorService.default()
        leaking.provider = AnswerLeakingProvider(leak=items[0].expected_answer)
        app.dependency_overrides[get_tutor_service] = lambda: leaking
        r = await c.post(
            f"{base}/attempts",
            json={"item_id": str(items[0].id), "answer": "9"},
            headers=headers("10B-02"),
        )
        print(f"  -> student saw: {r.json()['tutor_message'][:64]}")
        app.dependency_overrides.pop(get_tutor_service, None)

        print("10B-03 asks for the teacher:")
        r = await c.post(f"{base}/request-teacher", headers=headers("10B-03"))
        print(f"  -> {r.json()['status']}")

        print("teacher drills into 10B-01's transcript:")
        r = await c.get(
            f"/api/teacher/sessions/{session.id}/students/{students['10B-01'].id}/transcript",
            headers=headers("teacher-01"),
        )
        print(f"  -> {len(r.json())} evidence records read (and logged)")

        r = await c.get(
            f"/api/teacher/sessions/{session.id}/console", headers=headers("teacher-01")
        )
        queue = r.json()["queue"]
        print(f"\nteacher's queue now has {len(queue)} items:")
        for q in queue:
            print(f"  [{q['priority']}] {q['kind']:<28} {q['summary'][:60]}")

    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
