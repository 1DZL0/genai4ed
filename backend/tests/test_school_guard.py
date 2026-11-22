"""The guards a school day keeps to, and the test API it runs against. Nothing here reaches the
live site, OpenRouter or a database: each test sets the settings it needs, OpenRouter's key
endpoint is stood in for, and so are the API's process, the signals to it, the check that it is
up and the clock."""

import signal
import socket
import subprocess
from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from bench.school import guard, serve
from bench.school.guard import (
    FLOOR,
    Refused,
    affordable,
    check_target,
    copy_database_url,
    remaining,
)

# Imported by name on purpose, as the runner will import it: serve marks it as not a test, so
# pytest leaves it alone although its name starts with test_.
from bench.school.serve import server_env, test_server

LIVE = "postgresql+asyncpg://pact:hush-hush@127.0.0.1:5433/genai4ed"
COPY = "postgresql+asyncpg://pact:hush-hush@127.0.0.1:5433/genai4ed_memory"
ELSEWHERE = "postgresql+asyncpg://pact:hush-hush@db.example.com:5433/genai4ed"
KEY = "made-up"
BACKEND = Path(__file__).resolve().parents[1]
COMMAND = ["uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"]
# The real client, kept before any test stands in for it.
RealClient = httpx.AsyncClient
# The settings a run may set on the test API.
RUN_SETTINGS = ("DATABASE_URL", "DEMO_SIGN_IN", "COOKIE_SECURE", "OPENROUTER_MODEL", "AGENT_CLIENT")
# What a paid run on openai/gpt-5.6 sets; the agent is left to the app's own .env.
PAID = {
    "DATABASE_URL": COPY,
    "DEMO_SIGN_IN": "true",
    "COOKIE_SECURE": "false",
    "OPENROUTER_MODEL": "openai/gpt-5.6",
    "AGENT_CLIENT": None,
}
# Far past any real process id, so that a signal that somehow got past the stand-in for
# os.killpg could reach no process.
FAKE_PID = 1_000_000_000


@pytest.fixture
def live(monkeypatch):
    """The settings pointed at a made-up live database on this machine's Postgres."""
    monkeypatch.setattr(get_settings(), "database_url", LIVE)


@pytest.fixture
def other_way(monkeypatch):
    """This environment with each setting a run makes set the other way, so that a test sees the
    run's value only if the run set it: the suite's own environment (conftest) already has some
    of them the run's way."""
    monkeypatch.setenv("DATABASE_URL", ELSEWHERE)
    monkeypatch.setenv("DEMO_SIGN_IN", "false")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")
    monkeypatch.setenv("AGENT_CLIENT", "openrouter")


def _picked(env: dict[str, str]) -> dict[str, str | None]:
    """The settings a run sets, picked out of a whole environment, so that a failing test shows
    only these and never the rest of it."""
    return {name: env.get(name) for name in RUN_SETTINGS}


# ---------- where the run may go ----------


def test_the_live_ports_are_refused():
    for url in ("http://127.0.0.1:8000", "http://127.0.0.1:3000", "http://example.com:8010"):
        with pytest.raises(Refused):
            check_target(url)
    check_target("http://127.0.0.1:8010")


def test_only_a_named_port_on_this_machine_will_do():
    for url in ("http://localhost:8010", "http://10.0.0.5:8010", "http://127.0.0.1"):
        with pytest.raises(Refused):
            check_target(url)
    with pytest.raises(Refused):
        check_target("http://127.0.0.1:not-a-port")
    check_target("http://127.0.0.1:8011")


def test_the_copy_url_names_only_the_copy(monkeypatch):
    monkeypatch.setattr(get_settings(), "database_url", LIVE)
    assert copy_database_url() == COPY
    for url in (
        ELSEWHERE,
        "postgresql+asyncpg://pact:hush-hush@127.0.0.1:5432/genai4ed",
        "postgresql+asyncpg://pact:hush-hush@127.0.0.1:5433/genai4ed?host=db.example.com",
        # Parsed, the host is "x@127.0.0.1": it ends like the copy but is not this machine.
        "postgresql+asyncpg://pact:hush-hush@x@127.0.0.1:5433/genai4ed",
    ):
        monkeypatch.setattr(get_settings(), "database_url", url)
        with pytest.raises(Refused) as refused:
            copy_database_url()
        assert "hush" not in str(refused.value)


def test_a_database_url_that_cannot_be_read_is_refused_without_a_word_of_it(monkeypatch):
    # The parser's own error for this one quotes "quiet-word", a piece of the password.
    unreadable = "postgresql+asyncpg://pact:hush@hush:quiet-word/x@127.0.0.1:5433/genai4ed"
    monkeypatch.setattr(get_settings(), "database_url", unreadable)
    with pytest.raises(Refused) as refused:
        copy_database_url()
    assert "quiet-word" not in str(refused.value)
    assert refused.value.__context__ is None and refused.value.__cause__ is None


# ---------- money ----------


def test_money_stops_a_part_that_would_go_below_the_floor():
    assert affordable(8.0, 71.3) and not affordable(8.0, 22.0) and affordable(7.0, 22.0)
    assert FLOOR == 15.0 and affordable(8.0, 22.0, floor=10.0)


def _key_endpoint(monkeypatch, reply: httpx.Response | Exception) -> list[httpx.Request]:
    """Stands in for OpenRouter's key endpoint: every request is kept and gets `reply`, raised
    when it is an error. Nothing leaves the machine."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(
        guard.httpx,
        "AsyncClient",
        lambda **kwargs: RealClient(transport=httpx.MockTransport(answer), **kwargs),
    )
    return seen


async def test_the_money_left_is_read_from_the_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", KEY)
    key = {"data": {"limit": 250.0, "usage": 178.7, "limit_remaining": 71.3}}
    seen = _key_endpoint(monkeypatch, httpx.Response(200, json=key))
    assert await remaining() == 71.3
    (asked,) = seen
    assert str(asked.url) == "https://openrouter.ai/api/v1/key"
    assert asked.headers["Authorization"] == f"Bearer {KEY}"


async def test_money_that_cannot_be_read_stops_the_run(monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", KEY)
    for reply in (
        httpx.Response(401, json={"error": {"message": "No auth credentials found"}}),
        # A key with no limit: there is nothing to keep the floor against.
        httpx.Response(200, json={"data": {"limit": None, "limit_remaining": None}}),
        httpx.Response(200, text="<html>down for maintenance</html>"),
        httpx.ConnectError("no route to host"),
    ):
        _key_endpoint(monkeypatch, reply)
        with pytest.raises(Refused) as refused:
            await remaining()
        # Nothing is chained to the refusal: a failed request still holds the key in its header.
        assert KEY not in str(refused.value) and refused.value.__context__ is None
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "")
    seen = _key_endpoint(monkeypatch, httpx.Response(200, json={"data": {"limit_remaining": 9.0}}))
    with pytest.raises(Refused):
        await remaining()
    assert seen == []


# ---------- the test API ----------


def test_free_mode_runs_the_scripted_agent_and_keeps_the_model_alone(live, other_way):
    env = _picked(server_env(model=None, free=True))
    assert env == {
        "DATABASE_URL": COPY,
        "DEMO_SIGN_IN": "true",
        "COOKIE_SECURE": "false",
        # As this environment has it: the run chose no model.
        "OPENROUTER_MODEL": "anthropic/claude-sonnet-5",
        "AGENT_CLIENT": "scripted",
    }


def test_a_paid_run_sets_only_the_model_it_was_given(live, other_way, monkeypatch):
    # The agent this environment chooses (the suite's own is the scripted one) is dropped, so
    # the app's own .env decides, as on the live site.
    monkeypatch.setenv("AGENT_CLIENT", "scripted")
    monkeypatch.setenv("SUPERVISOR_ENFORCE", "true")
    whole = server_env(model="openai/gpt-5.6", free=False)
    env = _picked(whole)
    assert env == PAID
    # Everything else is this environment's, as it would be for the live API. Read out on its
    # own: pytest shows a failing assert's names, and `whole` holds the whole environment.
    enforce = whole.get("SUPERVISOR_ENFORCE")
    assert enforce == "true"


class FakeServer:
    """Stands in for the API's process: keeps how it was started and the signals sent to its
    process group, and runs nothing. `exits` is the code it has already exited with, if it has.
    A stubborn one ignores the request to stop and has to be killed. Of the environment it keeps
    only the run's own settings.

    Its group answers a signal as the real one does on macOS: once the process has exited, the
    group is gone if its exit has been collected, and before that a signal is refused with a
    permission error, the group holding nothing but the uncollected exit."""

    def __init__(
        self, command: list[str], kwargs: dict, pid: int, exits: int | None, stubborn: bool
    ):
        self.command = command
        self.settings = _picked(kwargs["env"])
        self.kwargs = {k: v for k, v in kwargs.items() if k != "env"}
        self.pid = pid
        self.returncode = exits
        self.stubborn = stubborn
        self.reaped = False
        self.signals: list[int] = []

    def poll(self) -> int | None:
        self.reaped = self.returncode is not None
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.command, timeout)
        self.reaped = True
        return self.returncode

    def signalled(self, sig: int) -> None:
        self.signals.append(sig)
        if self.returncode is not None:
            raise ProcessLookupError() if self.reaped else PermissionError()
        if sig == signal.SIGKILL or not self.stubborn:
            self.returncode = -sig


def _serve(
    monkeypatch, *, ready: bool = True, exits: int | None = None, stubborn: bool = False
) -> tuple[list[FakeServer], list[float]]:
    """Stands in for starting the API, for signalling its process group, for the check that it
    is up and for the clock: nothing starts, no real process is signalled, the port is not
    looked at and no time passes. Returns the processes as they start and the waits between
    checks."""
    started: list[FakeServer] = []
    waits: list[float] = []
    clock = [0.0]

    def popen(command, **kwargs):
        started.append(FakeServer(command, kwargs, FAKE_PID + len(started), exits, stubborn))
        return started[-1]

    def killpg(pgid, sig):
        # Only a stand-in's group can be signalled: any other id fails the test.
        (process,) = [p for p in started if p.pid == pgid]
        process.signalled(sig)

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(serve.subprocess, "Popen", popen)
    monkeypatch.setattr(serve.os, "killpg", killpg)
    monkeypatch.setattr(serve, "_ready", lambda base_url: ready)
    monkeypatch.setattr(serve, "_taken", lambda port: False)
    monkeypatch.setattr(serve, "sleep", sleep)
    monkeypatch.setattr(serve, "monotonic", lambda: clock[0])
    return started, waits


@pytest.mark.parametrize("failure", [RuntimeError("the run broke"), KeyboardInterrupt()])
def test_the_server_is_stopped_when_the_run_fails(live, monkeypatch, tmp_path, failure):
    started, _ = _serve(monkeypatch)
    with pytest.raises(type(failure)):
        with test_server(model=None, free=True, folder=tmp_path):
            raise failure
    assert started[0].signals == [signal.SIGTERM] and started[0].reaped


def test_a_server_that_died_during_the_run_does_not_hide_why_the_run_stopped(
    live, monkeypatch, tmp_path
):
    """Its group then holds only its uncollected exit, which macOS answers with a permission
    error: the stop takes that as nothing left to stop."""
    started, _ = _serve(monkeypatch)
    with pytest.raises(RuntimeError, match="the run broke"):
        with test_server(model=None, free=True, folder=tmp_path):
            started[0].returncode = 1
            raise RuntimeError("the run broke")
    assert started[0].signals == [signal.SIGTERM] and started[0].reaped


def test_the_server_runs_from_backend_on_the_copy_with_its_output_in_the_log(
    live, other_way, monkeypatch, tmp_path
):
    started, _ = _serve(monkeypatch)
    with test_server(model="openai/gpt-5.6", free=False, folder=tmp_path) as base_url:
        (process,) = started
        assert base_url == "http://127.0.0.1:8010" and process.signals == []
    assert process.signals == [signal.SIGTERM]
    assert process.command == COMMAND
    assert Path(process.kwargs["cwd"]) == BACKEND
    # A process group of its own, so that stopping the group stops uvicorn as well as uv.
    assert process.kwargs["start_new_session"] is True
    assert Path(process.kwargs["stdout"].name) == tmp_path / "server.log"
    assert process.kwargs["stderr"] == subprocess.STDOUT
    assert process.settings == PAID


def test_the_runner_must_say_where_the_log_goes(live, monkeypatch):
    started, _ = _serve(monkeypatch)
    with pytest.raises(TypeError):
        test_server(model=None, free=True)
    assert started == []


@pytest.mark.parametrize("exits, waited", [(None, 30.0), (1, 0.0)])
def test_a_server_that_does_not_come_up_is_stopped_and_its_log_named(
    live, monkeypatch, tmp_path, exits, waited
):
    """One that never answers is given 30 s; one that has already exited is not waited for, and
    its group having gone already does not hide why."""
    started, waits = _serve(monkeypatch, ready=False, exits=exits)
    with pytest.raises(serve.ServerDidNotStart) as failed:
        with test_server(model=None, free=True, folder=tmp_path):
            pytest.fail("the run went ahead with no API")
    assert str(tmp_path / "server.log") in str(failed.value)
    assert sum(waits) == waited and started[0].signals == [signal.SIGTERM]


def test_a_server_that_will_not_stop_when_asked_is_killed(live, monkeypatch, tmp_path):
    started, _ = _serve(monkeypatch, stubborn=True)
    with test_server(model=None, free=True, folder=tmp_path) as base_url:
        assert base_url.endswith(":8010")
    assert started[0].signals == [signal.SIGTERM, signal.SIGKILL] and started[0].reaped


def test_nothing_starts_when_a_guard_refuses(live, monkeypatch, tmp_path):
    started, _ = _serve(monkeypatch)
    with pytest.raises(Refused):
        with test_server(model=None, free=True, port=8000, folder=tmp_path):
            pytest.fail("the live API's port was used")
    monkeypatch.setattr(get_settings(), "database_url", ELSEWHERE)
    with pytest.raises(Refused):
        with test_server(model=None, free=True, folder=tmp_path):
            pytest.fail("a database that is not the copy was used")
    monkeypatch.setattr(get_settings(), "database_url", LIVE)
    monkeypatch.setattr(serve, "_taken", lambda port: True)
    with pytest.raises(Refused, match="already"):
        with test_server(model=None, free=True, folder=tmp_path):
            pytest.fail("an API already on the port was used")
    assert started == []


def test_a_port_in_use_is_seen():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert serve._taken(port)
    assert not serve._taken(port)


def test_the_server_is_up_only_when_it_says_demo_sign_in_is_on(monkeypatch):
    asked: list[str] = []
    for reply, up in (
        (httpx.Response(200, json={"demo_sign_in": True}), True),
        (httpx.Response(200, json={"demo_sign_in": False}), False),
        (httpx.Response(500, json={"demo_sign_in": True}), False),
        (httpx.Response(200, text="starting"), False),
        (httpx.ConnectError("connection refused"), False),
    ):

        def get(url, reply=reply, **kwargs):
            asked.append(url)
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(serve.httpx, "get", get)
        assert serve._ready("http://127.0.0.1:8010") is up
    assert set(asked) == {"http://127.0.0.1:8010/api/auth/config"}
