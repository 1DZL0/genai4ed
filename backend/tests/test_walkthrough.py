"""The guided walkthrough runs the pretend class through the real pipeline."""

import pytest

from app.config import get_settings


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_sign_in", True)
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)


async def test_walkthrough_is_off_outside_demo_mode(client, classroom):
    r = await client.post("/api/demo/walkthrough", headers=classroom.headers(classroom.teacher))
    assert r.status_code == 404


async def test_the_whole_walkthrough(client, demo_on):
    await client.post(
        "/api/auth/demo", json={"role": "teacher", "username": "prof", "password": "1"}
    )
    begun = (await client.post("/api/demo/walkthrough")).json()
    lesson = begun["lesson_id"]
    assert [c["profile"] for c in begun["cast"]] == [
        "confident",
        "gets_going",
        "language",
        "stuck",
        "hand_up",
        "quiet",
    ]

    assert (await client.post(f"/api/teacher/lessons/{lesson}/start")).status_code == 200
    # Tutors are off in the explanation: the pretend class can't ask yet.
    early = await client.post(
        f"/api/demo/lessons/{lesson}/simulate", json={"action": "start_writing"}
    )
    assert early.status_code == 409

    await client.post(
        f"/api/teacher/lessons/{lesson}/phase", json={"index": begun["writing_phase"]}
    )
    started = await client.post(
        f"/api/demo/lessons/{lesson}/simulate", json={"action": "start_writing"}
    )
    assert started.status_code == 200, started.text
    assert any("Have a go first" in line for line in started.json()["happened"])

    await client.post(f"/api/demo/lessons/{lesson}/simulate", json={"action": "get_stuck"})
    console = (await client.get(f"/api/teacher/sessions/{lesson}/console")).json()
    assert {q["kind"] for q in console["queue"]} >= {"stuck", "teacher_requested"}

    await client.post(f"/api/demo/lessons/{lesson}/simulate", json={"action": "hand_in"})
    scores = (await client.get(f"/api/teacher/lessons/{lesson}/scores")).json()
    assert len(scores) == 5

    quiet = begun["cast"][5]["student_id"]
    confident = begun["cast"][0]["student_id"]
    view = (await client.get(f"/api/demo/lessons/{lesson}/students/{confident}/view")).json()
    assert view["items"][0]["submitted"] is True
    assert view["items"][0]["score"] is None  # not until the teacher confirms
    quiet_view = (await client.get(f"/api/demo/lessons/{lesson}/students/{quiet}/view")).json()
    assert quiet_view["items"][0]["submitted"] is False
