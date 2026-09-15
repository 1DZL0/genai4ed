"""Designing a lesson by talking to the class agent."""

import io

from docx import Document
from sqlalchemy import select

from app.agent.llm import ScriptedClient, get_llm_client
from app.models import LessonContract, TutorTurn

PHOTOSYNTHESIS = (
    "I want to teach this class about photosynthesis. They already covered basic cell biology "
    "last week. Make this a 30-minute interactive activity."
)
RULE = (
    "Students can receive hints but should not receive the final answer until they have "
    "attempted the problem twice. If a student repeatedly tries to get the AI to complete the "
    "assignment for them, flag the interaction."
)


def teacher(classroom):
    return classroom.headers(classroom.teacher)


async def start(client, classroom, text=PHOTOSYNTHESIS):
    r = await client.post("/api/teacher/designs", json={"text": text}, headers=teacher(classroom))
    assert r.status_code == 201, r.text
    return r.json()


async def test_describing_a_lesson_drafts_a_brief(client, classroom):
    design = await start(client, classroom)
    assert design["status"] == "draft"
    assert design["brief"]["title"] == "Photosynthesis"
    assert design["brief"]["duration_minutes"] == 30
    assert "basic cell biology" in design["brief"]["prior_knowledge"]
    assert [m["role"] for m in design["messages"]] == ["teacher", "agent"]
    assert design["missing"] == []


async def test_a_rule_described_in_words_is_compiled_and_read_back(client, classroom):
    design = await start(client, classroom)
    r = await client.post(
        f"/api/teacher/designs/{design['id']}/messages",
        json={"text": RULE},
        headers=teacher(classroom),
    )
    rules = r.json()["brief"]["rules"]
    assert rules["full_answer_after_attempts"] == 2
    assert {"signal": "manipulation_attempt", "after": 2, "action": "alert"} in rules["escalations"]
    assert "The final answer only after 2 attempts." in r.json()["rules_in_words"]


async def test_approving_needs_a_complete_brief(client, classroom):
    empty = (
        await client.post("/api/teacher/designs", json={"text": ""}, headers=teacher(classroom))
    ).json()
    r = await client.post(f"/api/teacher/designs/{empty['id']}/approve", headers=teacher(classroom))
    assert r.status_code == 422
    assert "learning objective" in r.json()["detail"]


async def test_talking_about_an_approved_lesson_opens_a_new_draft(client, classroom):
    design = await start(client, classroom)
    approved = (
        await client.post(
            f"/api/teacher/designs/{design['id']}/approve", headers=teacher(classroom)
        )
    ).json()
    assert approved["status"] == "active"

    r = await client.post(
        f"/api/teacher/designs/{design['id']}/messages",
        json={"text": "Make it 20 minutes."},
        headers=teacher(classroom),
    )
    draft = r.json()
    assert (draft["version"], draft["status"]) == (2, "draft")
    assert draft["id"] != design["id"]
    assert draft["approved_version_id"] == design["id"]
    assert draft["brief"]["duration_minutes"] == 20
    # The conversation carries on across versions.
    assert len(draft["messages"]) == 4


async def test_an_approved_lesson_runs_for_its_length(client, classroom):
    design = await start(client, classroom)
    await client.post(f"/api/teacher/designs/{design['id']}/approve", headers=teacher(classroom))
    booked = await client.post(
        "/api/teacher/lessons",
        json={"plan_version_id": design["id"], "class_id": str(classroom.klass.id)},
        headers=teacher(classroom),
    )
    started = await client.post(
        f"/api/teacher/lessons/{booked.json()['lesson_id']}/start", headers=teacher(classroom)
    )
    lesson = started.json()
    from datetime import datetime

    minutes = (
        datetime.fromisoformat(lesson["closes_at"]) - datetime.fromisoformat(lesson["opened_at"])
    ).total_seconds() / 60
    assert round(minutes) == 30


async def test_uploaded_material_is_read_and_given_to_the_agent(client, app, classroom):
    design = await start(client, classroom)
    document = Document()
    document.add_paragraph("Chlorophyll absorbs light energy in the chloroplast.")
    buffer = io.BytesIO()
    document.save(buffer)

    uploaded = await client.post(
        f"/api/teacher/designs/{design['id']}/materials",
        files={"file": ("notes.docx", buffer.getvalue(), "application/octet-stream")},
        headers=teacher(classroom),
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["readable"] is True

    spy = ScriptedClient([{"reply": "Read it.", "brief": None}])
    app.dependency_overrides[get_llm_client] = lambda: spy
    await client.post(
        f"/api/teacher/designs/{design['id']}/messages",
        json={"text": "Use my notes.", "material_ids": [uploaded.json()["id"]]},
        headers=teacher(classroom),
    )
    assert "Chlorophyll absorbs light energy" in spy.calls[0]["system"]


async def test_unsupported_files_are_refused_plainly(client, classroom):
    design = await start(client, classroom)
    r = await client.post(
        f"/api/teacher/designs/{design['id']}/materials",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        headers=teacher(classroom),
    )
    assert r.status_code == 415


async def test_another_teacher_cannot_see_or_change_a_design(client, classroom):
    design = await start(client, classroom)
    other = classroom.headers(classroom.other_teacher)
    assert (
        await client.get(f"/api/teacher/designs/{design['id']}", headers=other)
    ).status_code == 404
    r = await client.post(
        f"/api/teacher/designs/{design['id']}/messages", json={"text": "hi"}, headers=other
    )
    assert r.status_code == 404


async def test_the_design_turn_is_audited(client, db, classroom):
    await start(client, classroom)
    turns = (await db.scalars(select(TutorTurn).where(TutorTurn.mode == "design"))).all()
    assert len(turns) == 1 and turns[0].context_manifest["mode"] == "design"


async def test_lessons_list_shows_drafts_and_approved(client, db, classroom):
    design = await start(client, classroom)
    cards = (await client.get("/api/teacher/designs", headers=teacher(classroom))).json()
    mine = next(c for c in cards if c["id"] == design["id"])
    assert (mine["status"], mine["steps"]) == ("draft", 4)
    assert await db.get(LessonContract, classroom.contract.id) is not None
