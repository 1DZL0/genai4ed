"""The opening of the tutor's prompt is the same for every pupil in a lesson: the rules, the
lesson and the teacher's material. It comes first and is marked for the provider to cache,
so a class of thirty pays for it in full once, not on every message."""

# ruff: noqa: F811 - fixtures

import json

import httpx
from pydantic import BaseModel

from app.agent import scaffold
from app.agent.llm import OpenRouterClient, ask_structured

from .test_moving_between_steps import THREE, three  # noqa: F401


class Out(BaseModel):
    reply: str


def _recording_client(model: str, seen: dict) -> OpenRouterClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"content": '{"reply": "ok"}'}}],
                "usage": {"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 6}},
            },
        )

    return OpenRouterClient(api_key="k", model=model, transport=httpx.MockTransport(handler))


async def test_the_shared_opening_is_marked_for_caching():
    seen: dict = {}
    client = _recording_client("anthropic/claude-opus-5.5", seen)
    _, result, _ = await ask_structured(
        client,
        Out,
        purpose="student_turn",
        system="THE SHARED RULES\n\nthis pupil only",
        cache_prefix="THE SHARED RULES",
        messages=[{"role": "user", "content": "x"}],
    )
    content = seen["body"]["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0] == {
        "type": "text",
        "text": "THE SHARED RULES",
        "cache_control": {"type": "ephemeral"},
    }
    # The model reads exactly the words it read before: only the marking is new.
    assert "".join(b["text"] for b in content).startswith("THE SHARED RULES\n\nthis pupil only")
    assert "cache_control" not in content[1]
    # What the provider reports about the cache is kept with the turn.
    assert result.usage["prompt_tokens_details"] == {"cached_tokens": 6}


async def test_nothing_is_marked_when_the_opening_does_not_match():
    seen: dict = {}
    client = _recording_client("anthropic/claude-opus-5.5", seen)
    await ask_structured(
        client,
        Out,
        purpose="student_turn",
        system="something else entirely",
        cache_prefix="THE SHARED RULES",
        messages=[{"role": "user", "content": "x"}],
    )
    assert isinstance(seen["body"]["messages"][0]["content"], str)


async def test_nothing_is_marked_for_a_model_that_is_not_claude():
    seen: dict = {}
    client = _recording_client("openai/gpt-5", seen)
    await ask_structured(
        client,
        Out,
        purpose="student_turn",
        system="THE SHARED RULES\n\nthis pupil only",
        cache_prefix="THE SHARED RULES",
        messages=[{"role": "user", "content": "x"}],
    )
    assert isinstance(seen["body"]["messages"][0]["content"], str)


def _prompt(index: int, attempts: int, now: str) -> str:
    return scaffold.assemble(
        brief=THREE,
        index=index,
        task=None,
        attempts=attempts,
        allowed=THREE.rules.allowed_disclosure(attempts),
        guidance=[],
        noticed=scaffold.Noticed(attempts=attempts, steps_after=2 - index),
        now=now,
        materials=[("Worksheet", "Solve each equation, showing your working.")],
    )


def test_every_pupil_in_a_lesson_gets_the_same_opening():
    shared = scaffold.shared(
        brief=THREE, materials=[("Worksheet", "Solve each equation, showing your working.")]
    )
    first = _prompt(0, 0, "The student has just opened the lesson.")
    other = _prompt(2, 3, "The student answered.")
    assert first.startswith(shared + "\n\n")
    assert other.startswith(shared + "\n\n")
    # The opening holds every fixed rule, the lesson and the material; nothing about one pupil.
    for part in scaffold.fixed_parts()[1:]:
        assert part in shared
    assert "Linear equations" in shared
    assert "showing your working" in shared
    assert "\n\nThis step\n" not in shared
    assert "\n\nAllowed right now\n" not in shared
    assert "\n\nRight now\n" not in shared


async def test_a_tutor_turn_sends_the_shared_opening_to_be_cached(db, client, three):
    from .test_moving_between_steps import OPEN, script, start

    script(three, OPEN)
    await start(client, three)
    call = next(c for c in three.tutor.calls if c["purpose"] == "student_turn")
    assert call["cache_prefix"]
    assert call["system"].startswith(call["cache_prefix"] + "\n\n")
    assert "Linear equations" in call["cache_prefix"]
