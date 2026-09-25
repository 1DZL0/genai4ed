"""The language model behind the class agent.

`OpenRouterClient` reaches a hosted model; `ScriptedClient` answers without one.
Every call asks for JSON, which `ask_structured` validates against a pydantic model.
"""

import base64
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    """The model could not be reached, or never produced a usable reply."""

    # What the model said, when it said something unusable.
    raw: str = ""


class MalformedReply(LLMError):
    def __init__(self, raw: str, *, truncated: bool = False) -> None:
        super().__init__(
            "The model's reply was cut off before the end."
            if truncated
            else "The model's reply wasn't valid JSON."
        )
        self.raw = raw
        # Cut off means the retry needs to be shorter, not different.
        self.truncated = truncated


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


_SCHEMA_PROSE = frozenset({"title", "description", "examples", "default"})


def bare_schema(node):
    """The schema without its prose (titles, descriptions, examples, defaults)."""
    if isinstance(node, dict):
        return {k: bare_schema(v) for k, v in node.items() if k not in _SCHEMA_PROSE}
    if isinstance(node, list):
        return [bare_schema(v) for v in node]
    return node


# A provider saying the response format itself is unusable, not that the request is wrong.
_SCHEMA_REFUSED = re.compile(
    r"too many states|schema (is )?(too|not)|constraint|response_format|json_schema|"
    r"structured outputs?|unsupported",
    re.IGNORECASE,
)

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


# Models that refused JSON mode, remembered so the refusal is paid for once per process.
_no_json_mode: set[str] = set()

_JSON_REMINDER = "(Reply with the JSON object only - nothing outside it.)"


def _reminded(messages: list[dict]) -> list[dict]:
    """The messages with the ask for JSON repeated at the very end; what is stored is unchanged."""
    if not messages or messages[-1]["role"] != "user":
        return [*messages, {"role": "user", "content": _JSON_REMINDER}]
    last = messages[-1]
    content = last["content"]
    content = (
        f"{content}\n\n{_JSON_REMINDER}"
        if isinstance(content, str)
        else [*content, {"type": "text", "text": _JSON_REMINDER}]
    )
    return [*messages[:-1], {**last, "content": content}]


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
            "messages": [{"role": "system", "content": system}, *_reminded(messages)],
            "max_tokens": max_tokens,
            "temperature": 0.4,
            # Pseudonymous pupil data still shouldn't train anyone's model.
            "provider": {"data_collection": "deny"},
        }
        if self.model not in _no_json_mode:
            payload["response_format"] = {"type": "json_object"}
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

        failed = response.status_code
        if failed == 200 and isinstance(response.json().get("error"), dict):
            # OpenRouter reports some failures as a 200 with the error inside.
            failed = int(response.json()["error"].get("code") or 502)
        if failed != 200:
            detail = response.text[:300]
            if failed == 400 and self.model not in _no_json_mode and _SCHEMA_REFUSED.search(detail):
                # This model won't take JSON mode: ask in words; the reply is validated anyway.
                _no_json_mode.add(self.model)
                return await self.complete(
                    purpose=purpose,
                    system=system,
                    messages=messages,
                    schema=schema,
                    max_tokens=max_tokens,
                )
            raise LLMError(f"The model service answered {failed}: {detail}")
        body = response.json()
        try:
            choice = body["choices"][0]
            raw = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("The model service sent a reply with no message.") from exc
        try:
            data = parse_json(raw)
        except json.JSONDecodeError as exc:
            cut = choice.get("finish_reason") == "length" or not raw.strip()
            raise MalformedReply(raw, truncated=cut) from exc
        return LLMResult(
            data=data,
            raw=raw,
            provider=self.name,
            model=str(body.get("model") or self.model),
            latency_ms=latency,
            usage=body.get("usage") or {},
        )


class ScriptedClient:
    """Answers without a model: from a list of replies (tests) or a function of
    (purpose, system, messages) (the keyless demo)."""

    name = "scripted"

    def __init__(
        self, replies: list[dict] | Callable[[str, str, list[dict]], dict], model: str = "scripted"
    ) -> None:
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
    """One validated reply as (value, result, attempts); a bad reply is sent back once."""
    schema = bare_schema(output.model_json_schema())
    instruction = (
        f"{system}\n\nReply with a single JSON object and nothing else. It must match this "
        f"JSON schema:\n{json.dumps(schema)}"
    )
    conversation = list(messages)
    problem = ""
    raw = ""
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
            raw = exc.raw
            problem = (
                "Your reply ran past the room available and was cut off. Answer again, "
                "much shorter: a sentence or two of prose at most."
                if exc.truncated
                else "Your reply was not valid JSON."
            )
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
    # The unusable reply travels with the error so the audit row can keep it.
    failure = LLMError(problem or "No usable reply.")
    failure.raw = raw
    raise failure


def get_llm_client() -> LLMClient:
    """The configured client; with no OpenRouter key, the scripted demo agent."""
    settings = get_settings()
    choice = settings.agent_client
    if choice == "openrouter" or (choice == "auto" and settings.openrouter_api_key):
        if not settings.openrouter_api_key:
            raise LLMError("AGENT_CLIENT is openrouter but OPENROUTER_API_KEY is not set.")
        return OpenRouterClient(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            timeout=settings.openrouter_timeout_s,
        )
    from app.agent.scripted import demo_responder

    return ScriptedClient(demo_responder, model="scripted-demo")
