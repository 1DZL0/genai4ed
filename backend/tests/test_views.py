"""What the redesigned pages are given to draw.

The student's page is rebuilt from their own history, so a reload loses
nothing; the teacher's register shows, per student and question, how far up the
ladder the tutor has gone. The student side must never learn the expected
answer or the rung - those stay on the teacher's side of the desk.
"""


async def submit(client, classroom, answer, student=None):
    return await client.post(
        f"/api/sessions/{classroom.session.id}/attempts",
        json={"item_id": str(classroom.item.id), "answer": answer},
        headers=classroom.headers(student or classroom.alice),
    )


async def student_view(client, classroom, student=None):
    return (
        await client.get(
            f"/api/sessions/{classroom.session.id}",
            headers=classroom.headers(student or classroom.alice),
        )
    ).json()


async def console(client, classroom):
    return (
        await client.get(
            f"/api/teacher/sessions/{classroom.session.id}/console",
            headers=classroom.headers(classroom.teacher),
        )
    ).json()


async def test_a_reload_brings_back_the_students_own_work(client, classroom):
    await submit(client, classroom, "4")
    await submit(client, classroom, "5")

    body = await student_view(client, classroom)
    [item] = body["items"]
    assert body["subject"] == "mathematics"
    assert item["solved"] is True
    assert item["attempts"] == 2
    assert [(h["kind"], h["correct"]) for h in item["history"]] == [
        ("attempt", False),
        ("hint", None),
        ("attempt", True),
    ]
    assert item["history"][0]["text"] == "4"


async def test_the_students_history_never_carries_the_answer_or_the_rung(client, classroom):
    await submit(client, classroom, "4")
    body = await student_view(client, classroom)
    text = str(body)
    assert "expected" not in text
    assert "rung" not in text
    assert "partial_step" not in text and "diagnostic_question" not in text


async def test_a_student_sees_only_their_own_history(client, classroom):
    await submit(client, classroom, "4")
    [item] = (await student_view(client, classroom, student=classroom.bob))["items"]
    assert item["history"] == []


async def test_a_message_from_the_teacher_reaches_the_student(client, classroom):
    await client.post(
        f"/api/teacher/sessions/{classroom.session.id}/students/{classroom.alice.id}/message",
        json={"text": "Nice work, try question 2 next."},
        headers=classroom.headers(classroom.teacher),
    )
    body = await student_view(client, classroom)
    assert [m["text"] for m in body["teacher_messages"]] == ["Nice work, try question 2 next."]
    assert (await student_view(client, classroom, student=classroom.bob))["teacher_messages"] == []


async def test_the_register_shows_ladder_position_per_question(client, classroom):
    await submit(client, classroom, "4")
    await submit(client, classroom, "6")

    body = await console(client, classroom)
    assert body["subject"] == "mathematics"
    assert body["class_label"] == "10B"
    assert [i["ordinal"] for i in body["item_list"]] == [1]
    assert body["rungs"][0] == "attempt"

    alice, bob = body["progress"]
    [cell] = alice["cells"]
    assert cell["attempts"] == 2
    assert cell["solved"] is False
    assert cell["rung"] == "conceptual_cue"
    bob_cell = bob["cells"][0]
    assert bob_cell["item_id"] == str(classroom.item.id)
    assert bob_cell["kind"] == "short_answer"
    assert (bob_cell["attempts"], bob_cell["solved"], bob_cell["rung"]) == (0, False, None)


async def test_the_register_marks_who_is_waiting_for_the_teacher(client, classroom):
    await client.post(
        f"/api/sessions/{classroom.session.id}/request-teacher",
        headers=classroom.headers(classroom.bob),
    )
    alice, bob = (await console(client, classroom))["progress"]
    assert (alice["needs_you"], bob["needs_you"]) == (False, True)
