"""Lesson plans: writing, approving, versioning, reusing and deleting.

The governance the platform enforces is only as good as the teacher's ability
to set it, so these check that what she writes is what actually binds - and
that editing or deleting a plan never rewrites the record of a lesson already
taught with it.
"""

import uuid

from sqlalchemy import select

from app.enums import ContractStatus, Rung
from app.models import ContractItem, LessonContract

WITHHELD = {"max_rung": Rung.PARTIAL_STEP.value, "allow_full_solution": False}


def plan_body(**overrides):
    body = {
        "title": "Expanding brackets",
        "subject": "mathematics",
        "objective_code": "ALG-L5",
        "objective_title": "Expand and simplify",
        "notes": "Worked examples on the board first.",
        "items": [
            {
                "prompt": "Expand: 3(x + 4)",
                "expected_answer": "3x + 12",
                "hint_templates": {
                    Rung.DIAGNOSTIC_QUESTION.value: "What does the 3 multiply?",
                    Rung.TARGETED_HINT.value: "Every term inside the bracket.",
                },
                "misconception_vocabulary": [
                    {"code": "expands_partially", "label": "Multiplies only the first term"}
                ],
            }
        ],
        **WITHHELD,
    }
    body.update(overrides)
    return body


async def create(client, classroom, teacher=None, **overrides):
    return await client.post(
        "/api/teacher/plans",
        json=plan_body(**overrides),
        headers=classroom.headers(teacher or classroom.teacher),
    )


async def post(client, classroom, path, teacher=None):
    return await client.post(path, headers=classroom.headers(teacher or classroom.teacher))


async def approved_plan(client, classroom):
    created = (await create(client, classroom)).json()
    await post(client, classroom, f"/api/teacher/plans/{created['id']}/approve")
    return created


async def library(client, classroom, **params):
    return (
        await client.get(
            "/api/teacher/plans", params=params, headers=classroom.headers(classroom.teacher)
        )
    ).json()


# ---------- writing and approving ----------


async def test_a_new_plan_is_a_draft_that_governs_nobody_yet(client, classroom):
    response = await create(client, classroom)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ContractStatus.DRAFT.value
    assert body["version"] == 1
    assert body["items"] == 1
    assert body["approved_version_id"] is None
    assert body["used_with"] == []


async def test_a_plan_has_a_default_timeline_with_tutor_time_in_the_middle(client, classroom):
    created = (await create(client, classroom)).json()
    detail = (
        await client.get(
            f"/api/teacher/plans/{created['id']}", headers=classroom.headers(classroom.teacher)
        )
    ).json()
    assert [p["tutors_on"] for p in detail["timeline"]] == [False, True, False]
    assert created["minutes"] == 50


async def test_a_timeline_without_tutor_time_is_refused(client, classroom):
    response = await create(
        client, classroom, timeline=[{"name": "Lecture", "minutes": 40, "tutors_on": False}]
    )
    assert response.status_code == 422


async def test_approving_records_who_approved_it_and_when(client, classroom, db):
    created = (await create(client, classroom)).json()
    response = await post(client, classroom, f"/api/teacher/plans/{created['id']}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == ContractStatus.ACTIVE.value
    assert response.json()["approved_version_id"] == created["id"]

    contract = await db.get(LessonContract, uuid.UUID(created["id"]))
    await db.refresh(contract)
    assert contract.activated_by == classroom.teacher.id
    assert contract.activated_at is not None


async def test_a_draft_can_be_edited_in_place(client, classroom):
    created = (await create(client, classroom)).json()
    response = await client.put(
        f"/api/teacher/plans/{created['id']}",
        json=plan_body(title="Expanding double brackets"),
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Expanding double brackets"
    assert response.json()["version"] == 1


async def test_an_approved_version_cannot_be_changed_in_place(client, classroom):
    created = await approved_plan(client, classroom)
    response = await client.put(
        f"/api/teacher/plans/{created['id']}",
        json=plan_body(title="Sneaky change"),
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 409


async def test_the_ladder_she_chooses_is_the_ladder_that_binds(client, classroom, db):
    """A plan capped at conceptual_cue must not contain the rungs above it."""
    created = (await create(client, classroom, max_rung=Rung.CONCEPTUAL_CUE.value)).json()
    contract = await db.get(LessonContract, uuid.UUID(created["id"]))
    assert contract.assistance_ladder["rungs"] == [
        Rung.ATTEMPT.value,
        Rung.DIAGNOSTIC_QUESTION.value,
        Rung.CONCEPTUAL_CUE.value,
    ]


async def test_the_full_solution_needs_explicit_permission(client, classroom):
    response = await create(
        client, classroom, max_rung=Rung.FULL_SOLUTION.value, allow_full_solution=False
    )
    assert response.status_code == 422
    assert "allow_full_solution" in response.json()["detail"]


async def test_a_hint_cannot_be_written_for_a_rung_that_does_not_exist(client, classroom):
    body = plan_body()
    body["items"][0]["hint_templates"] = {"whisper_the_answer": "psst"}
    response = await client.post(
        "/api/teacher/plans", json=body, headers=classroom.headers(classroom.teacher)
    )
    assert response.status_code == 422


async def test_a_student_cannot_write_a_plan(client, classroom):
    assert (await create(client, classroom, teacher=classroom.alice)).status_code == 403


async def test_a_teacher_cannot_see_or_touch_another_teachers_plan(client, classroom):
    created = (await create(client, classroom)).json()
    other = classroom.headers(classroom.other_teacher)
    assert (
        await client.get(f"/api/teacher/plans/{created['id']}", headers=other)
    ).status_code == 404
    assert (
        await client.post(f"/api/teacher/plans/{created['id']}/approve", headers=other)
    ).status_code == 404
    assert (
        await client.delete(f"/api/teacher/plans/{created['id']}", headers=other)
    ).status_code == 404
    assert (await client.get("/api/teacher/plans", headers=other)).json() == []


# ---------- versions ----------


async def test_editing_an_approved_plan_makes_the_next_version(client, classroom):
    v1 = await approved_plan(client, classroom)
    response = await post(client, classroom, f"/api/teacher/plans/{v1['id']}/versions")
    assert response.status_code == 201
    v2 = response.json()
    assert v2["plan_id"] == v1["plan_id"]
    assert v2["version"] == 2
    assert v2["status"] == ContractStatus.DRAFT.value
    # Version 1 can still be taught while version 2 is being written.
    assert v2["approved_version_id"] == v1["id"]
    assert v2["items"] == 1


async def test_asking_twice_for_a_new_version_reuses_the_open_draft(client, classroom):
    v1 = await approved_plan(client, classroom)
    first = (await post(client, classroom, f"/api/teacher/plans/{v1['id']}/versions")).json()
    second = (await post(client, classroom, f"/api/teacher/plans/{v1['id']}/versions")).json()
    assert first["id"] == second["id"]


async def test_approving_a_new_version_retires_the_old_one(client, classroom, db):
    v1 = await approved_plan(client, classroom)
    v2 = (await post(client, classroom, f"/api/teacher/plans/{v1['id']}/versions")).json()
    approved = (await post(client, classroom, f"/api/teacher/plans/{v2['id']}/approve")).json()
    assert approved["approved_version"] == 2

    old = await db.get(LessonContract, uuid.UUID(v1["id"]))
    await db.refresh(old)
    assert old.status == ContractStatus.CLOSED.value


def rows_for(rows, plan):
    """The classroom fixture already owns a plan, so pick out the one under test."""
    return [r for r in rows if r["plan_id"] == plan["plan_id"]]


async def test_the_library_shows_one_row_per_plan_at_its_newest_version(client, classroom):
    v1 = await approved_plan(client, classroom)
    await post(client, classroom, f"/api/teacher/plans/{v1['id']}/versions")
    [row] = rows_for(await library(client, classroom), v1)
    assert row["version"] == 2


async def test_the_library_filters_and_searches(client, classroom):
    await approved_plan(client, classroom)
    await create(client, classroom, title="Simultaneous equations")
    assert [r["title"] for r in await library(client, classroom, status="draft")] == [
        "Simultaneous equations"
    ]
    # The fixture's "Linear equations" plan is approved too.
    assert sorted(r["title"] for r in await library(client, classroom, status="approved")) == [
        "Expanding brackets",
        "Linear equations",
    ]
    assert [r["title"] for r in await library(client, classroom, q="simult")] == [
        "Simultaneous equations"
    ]


async def test_duplicating_makes_a_separate_draft_plan(client, classroom, db):
    v1 = await approved_plan(client, classroom)
    response = await post(client, classroom, f"/api/teacher/plans/{v1['id']}/duplicate")
    assert response.status_code == 201
    copy = response.json()
    assert copy["plan_id"] != v1["plan_id"]
    assert copy["title"] == "Copy of Expanding brackets"
    assert copy["status"] == ContractStatus.DRAFT.value
    items = (
        await db.scalars(
            select(ContractItem).where(ContractItem.contract_id == uuid.UUID(copy["id"]))
        )
    ).all()
    assert [i.prompt for i in items] == ["Expand: 3(x + 4)"]


# ---------- deleting ----------


async def test_deleting_an_unused_plan_removes_it_for_good(client, classroom, db):
    created = (await create(client, classroom)).json()
    response = await client.delete(
        f"/api/teacher/plans/{created['id']}", headers=classroom.headers(classroom.teacher)
    )
    assert response.json()["outcome"] == "deleted"
    assert await db.get(LessonContract, uuid.UUID(created["id"])) is None


async def test_deleting_a_newer_draft_keeps_the_approved_version(client, classroom):
    v1 = await approved_plan(client, classroom)
    v2 = (await post(client, classroom, f"/api/teacher/plans/{v1['id']}/versions")).json()
    await client.delete(
        f"/api/teacher/plans/{v2['id']}", headers=classroom.headers(classroom.teacher)
    )
    [row] = rows_for(await library(client, classroom), v1)
    assert row["id"] == v1["id"]
    assert row["version"] == 1


async def test_deleting_a_used_plan_archives_it_and_keeps_the_lesson(client, classroom, db):
    """The classroom fixture's contract has already been taught (it has a session)."""
    response = await client.delete(
        f"/api/teacher/plans/{classroom.contract.id}", headers=classroom.headers(classroom.teacher)
    )
    assert response.json()["outcome"] == "archived"
    assert await library(client, classroom) == []

    kept = await db.get(LessonContract, classroom.contract.id)
    await db.refresh(kept)
    assert kept.archived_at is not None

    restored = await post(client, classroom, f"/api/teacher/plans/{classroom.contract.id}/restore")
    assert restored.json()["archived"] is False
    assert len(await library(client, classroom)) == 1
