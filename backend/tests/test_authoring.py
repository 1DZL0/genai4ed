"""Lesson contract authoring.

The governance the platform enforces is only as good as the teacher's ability
to set it, so these check that what she authors is what actually binds.
"""

import uuid

from app.enums import ContractStatus, Rung

WITHHELD = {
    "max_rung": Rung.PARTIAL_STEP.value,
    "allow_full_solution": False,
}


def draft(classroom, **overrides):
    body = {
        "title": "Expanding brackets",
        "subject": "mathematics",
        "objective_code": "ALG-L5",
        "objective_title": "Expand and simplify",
        "class_id": str(classroom.klass.id),
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


async def test_a_teacher_authors_a_draft_that_governs_nobody_yet(client, classroom):
    response = await client.post(
        "/api/teacher/contracts",
        json=draft(classroom),
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ContractStatus.DRAFT.value
    assert body["items"] == 1
    assert body["allow_full_solution"] is False


async def test_a_draft_cannot_have_a_session_opened_for_it(client, classroom):
    created = (
        await client.post(
            "/api/teacher/contracts",
            json=draft(classroom),
            headers=classroom.headers(classroom.teacher),
        )
    ).json()

    response = await client.post(
        f"/api/teacher/contracts/{created['id']}/sessions",
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 409
    assert "Activate" in response.json()["detail"]


async def test_activating_records_who_approved_it_and_when(client, classroom, db):
    created = (
        await client.post(
            "/api/teacher/contracts",
            json=draft(classroom),
            headers=classroom.headers(classroom.teacher),
        )
    ).json()

    response = await client.post(
        f"/api/teacher/contracts/{created['id']}/activate",
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 200
    assert response.json()["status"] == ContractStatus.ACTIVE.value

    from app.models import LessonContract

    contract = await db.get(LessonContract, uuid.UUID(created["id"]))
    await db.refresh(contract)
    assert contract.activated_by == classroom.teacher.id
    assert contract.activated_at is not None


async def test_opening_a_session_admits_the_whole_class(client, classroom):
    created = (
        await client.post(
            "/api/teacher/contracts",
            json=draft(classroom),
            headers=classroom.headers(classroom.teacher),
        )
    ).json()
    await client.post(
        f"/api/teacher/contracts/{created['id']}/activate",
        headers=classroom.headers(classroom.teacher),
    )

    response = await client.post(
        f"/api/teacher/contracts/{created['id']}/sessions?minutes=30",
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 201
    # Alice and Bob are enrolled; the outsider is not.
    assert response.json()["students"] == 2


async def test_the_ladder_she_chooses_is_the_ladder_that_binds(client, classroom, db):
    """A contract capped at conceptual_cue must not contain the rungs above it."""
    created = (
        await client.post(
            "/api/teacher/contracts",
            json=draft(classroom, max_rung=Rung.CONCEPTUAL_CUE.value),
            headers=classroom.headers(classroom.teacher),
        )
    ).json()

    from app.models import LessonContract

    contract = await db.get(LessonContract, uuid.UUID(created["id"]))
    assert contract.assistance_ladder["rungs"] == [
        Rung.ATTEMPT.value,
        Rung.DIAGNOSTIC_QUESTION.value,
        Rung.CONCEPTUAL_CUE.value,
    ]
    assert Rung.PARTIAL_STEP.value not in contract.assistance_ladder["rungs"]


async def test_the_full_solution_needs_explicit_permission(client, classroom):
    """Asking for the full-solution rung without setting allow_full_solution is
    a contradiction, and is refused while she is still looking at the form."""
    response = await client.post(
        "/api/teacher/contracts",
        json=draft(classroom, max_rung=Rung.FULL_SOLUTION.value, allow_full_solution=False),
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 422
    assert "allow_full_solution" in response.json()["detail"]


async def test_a_hint_cannot_be_written_for_a_rung_that_does_not_exist(client, classroom):
    body = draft(classroom)
    body["items"][0]["hint_templates"] = {"whisper_the_answer": "psst"}
    response = await client.post(
        "/api/teacher/contracts", json=body, headers=classroom.headers(classroom.teacher)
    )
    assert response.status_code == 422


async def test_a_teacher_cannot_author_for_another_teachers_class(client, classroom):
    response = await client.post(
        "/api/teacher/contracts",
        json=draft(classroom),
        headers=classroom.headers(classroom.other_teacher),
    )
    assert response.status_code == 404


async def test_a_student_cannot_author_a_contract(client, classroom):
    response = await client.post(
        "/api/teacher/contracts",
        json=draft(classroom),
        headers=classroom.headers(classroom.alice),
    )
    assert response.status_code == 403
