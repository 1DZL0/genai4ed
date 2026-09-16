"""The guided walkthrough runs a pretend class through the real class agent loop."""

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
        "unsure",
        "misconception",
        "misconception_2",
        "rule_tester",
        "asks_questions",
    ]

    early = await client.post(f"/api/demo/lessons/{lesson}/simulate", json={"action": "open"})
    assert early.status_code == 409
    assert (await client.post(f"/api/teacher/lessons/{lesson}/start")).status_code == 200

    for action in ("open", "work", "push"):
        r = await client.post(f"/api/demo/lessons/{lesson}/simulate", json={"action": action})
        assert r.status_code == 200, r.text

    live = (await client.get(f"/api/teacher/live/{lesson}")).json()
    kinds = {a["kind"] for a in live["alerts"]}
    assert "manipulation" in kinds
    assert [p["note"] for p in live["patterns"]] == ["Thinks plants get their food from the soil"]

    await client.post(f"/api/demo/lessons/{lesson}/simulate", json={"action": "finish"})
    live = (await client.get(f"/api/teacher/live/{lesson}")).json()
    states = {s["pseudonym"]: s["state"] for s in live["students"]}
    assert states[begun["cast"][0]["pseudonym"]] == "finished"

    await client.post(f"/api/teacher/sessions/{lesson}/state", params={"to": "closed"})
    review = (await client.post(f"/api/teacher/live/{lesson}/outcomes")).json()
    assert len(review["outcomes"]) == 6
