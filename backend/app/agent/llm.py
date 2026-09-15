"""The language model behind the class agent.

`LLMClient` is the seam. `OpenRouterClient` reaches a hosted model through
OpenRouter's OpenAI-compatible API; `ScriptedClient` answers without any model,
for the test suite and for demos run with no API key.

Every call asks for JSON and gets it validated by the caller against a pydantic
model. Models don't always honour a response schema, so the schema is also
stated in the system prompt and a malformed reply is retried once with the
validation error attached - rather than trusting one mechanism.
"""

import base64
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    """The model could not be reached, or never produced a usable reply."""


@dataclass(frozen=True)
class LLMResult:
    data: dict
    raw: str
    provider: str
    model: str
    latency_ms: int
    usage: dict = field(default_factory=dict)


class LLMClient(Protocol):
    name: str
    model: str

    async def complete(
        self,
        *,
        purpose: str,
        system: str,
        messages: list[dict],
        schema: dict,
        max_tokens: int,
    ) -> LLMResult: ...


def image_part(media_type: str, content: bytes) -> dict:
    """An image the model is shown directly, in OpenAI message format."""
    encoded = base64.b64encode(content).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}}


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json(text: str) -> dict:
    """The JSON object in a reply, tolerating a code fence or leading prose."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise json.JSONDecodeError("expected a JSON object", cleaned, 0)
    return value


class OpenRouterClient:
    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def complete(
        self,
        *,
        purpose: str,
        system: str,
        messages: list[dict],
        schema: dict,
        max_tokens: int,
    ) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": purpose, "strict": False, "schema": schema},
            },
            "max_tokens": max_tokens,
            "temperature": 0.4,
            # Pseudonymous pupil data still shouldn't train anyone's model.
            "provider": {"data_collection": "deny"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-Title": "GenAI4ED",
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"Couldn't reach the model: {exc.__class__.__name__}") from exc
        latency = int((time.perf_counter() - started) * 1000)

        if response.status_code != 200:
            detail = response.text[:300]
            raise LLMError(f"The model service answered {response.status_code}: {detail}")
        body = response.json()
        try:
            raw = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("The model service sent a reply with no message.") from exc
        try:
            data = parse_json(raw)
        except json.JSONDecodeError as exc:
            raise MalformedReply(raw) from exc
        return LLMResult(
            data=data,
            raw=raw,
            provider=self.name,
            model=str(body.get("model") or self.model),
            latency_ms=latency,
            usage=body.get("usage") or {},
        )


class MalformedReply(LLMError):
    def __init__(self, raw: str) -> None:
        super().__init__("The model's reply wasn't valid JSON.")
        self.raw = raw


Responder = Callable[[str, str, list[dict]], dict]


class ScriptedClient:
    """Answers without a model.

    Given a list, replies with each dict in turn - what a test wants. Given a
    function, calls it with (purpose, system, messages) - what the keyless demo
    uses (`app.agent.scripted`).
    """

    name = "scripted"

    def __init__(self, replies: list[dict] | Responder, model: str = "scripted") -> None:
        self.model = model
        self.calls: list[dict] = []
        self._replies = replies

    async def complete(
        self,
        *,
        purpose: str,
        system: str,
        messages: list[dict],
        schema: dict,
        max_tokens: int,
    ) -> LLMResult:
        self.calls.append({"purpose": purpose, "system": system, "messages": messages})
        if callable(self._replies):
            data = self._replies(purpose, system, messages)
        else:
            if not self._replies:
                raise LLMError("The scripted client has no reply left.")
            data = self._replies.pop(0)
        return LLMResult(
            data=data,
            raw=json.dumps(data),
            provider=self.name,
            model=self.model,
            latency_ms=0,
        )


async def ask_structured[T: BaseModel](
    client: LLMClient,
    output: type[T],
    *,
    purpose: str,
    system: str,
    messages: list[dict],
    max_tokens: int = 1500,
    check: Callable[[T], None] | None = None,
) -> tuple[T, LLMResult, int]:
    """One structured reply, validated. Returns (value, result, attempts).

    A reply that isn't valid JSON, doesn't fit `output`, or fails `check` is
    sent back once with the problem stated. A second failure raises LLMError.
    """
    schema = output.model_json_schema()
    instruction = (
        f"{system}\n\nReply with a single JSON object and nothing else. It must match this "
        f"JSON schema:\n{json.dumps(schema)}"
    )
    conversation = list(messages)
    problem = ""
    for attempt in (1, 2):
        try:
            result = await client.complete(
                purpose=purpose,
                system=instruction,
                messages=conversation,
                schema=schema,
                max_tokens=max_tokens,
            )
        except MalformedReply as exc:
            problem, raw = "Your reply was not valid JSON.", exc.raw
        else:
            try:
                value = output.model_validate(result.data)
                if check is not None:
                    check(value)
                return value, result, attempt
            except (ValidationError, ValueError) as exc:
                problem = f"Your reply did not fit what was asked: {str(exc)[:600]}"
                raw = result.raw
        if attempt == 1:
            conversation = [
                *messages,
                {"role": "assistant", "content": raw[:4000]},
                {"role": "user", "content": f"{problem} Send the corrected JSON object only."},
            ]
    raise LLMError(problem or "No usable reply.")


def get_llm_client() -> LLMClient:
    """The configured client. With no OpenRouter key the scripted demo agent
    answers, so the platform still runs end to end."""
    settings = get_settings()
    choice = settings.agent_client
    if choice == "openrouter" or (choice == "auto" and settings.openrouter_api_key):
        if not settings.openrouter_api_key:
            raise LLMError("AGENT_CLIENT is openrouter but OPENROUTER_API_KEY is not set.")
        return OpenRouterClient(
            api_key=settings.openrouter_api_key, model=settings.openrouter_model
        )
    from app.agent.scripted import demo_responder

    return ScriptedClient(demo_responder, model="scripted-demo")


def describe(client: Any) -> dict:
    return {"provider": getattr(client, "name", "unknown"), "model": getattr(client, "model", "")}
