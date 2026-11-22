"""The test API a school day runs against: started for the run and stopped when it ends.

It is the platform's own API, started from backend/ with `uv run uvicorn` on 127.0.0.1 (port
8010 unless told otherwise), with three of its settings changed and no more: the copy database,
demo sign-in on (the run's teachers and pupils sign in the way anyone does at a demo), and
cookies that work over plain http. A run may also choose the model, or, in free mode, the
scripted demo agent, so that no model is called. Every other setting is the live site's, read
from the same .env.

It runs in a process group of its own, and stopping it stops the whole group: uv, and the
uvicorn that uv starts. Its output goes to server.log in the run's folder, never to the
console. Its environment holds the database URL, so it is never printed.
"""

import os
import signal
import socket
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

import httpx

from bench.school.guard import LOCAL_HOST, TEST_PORT, Refused, check_target, copy_database_url

BACKEND = Path(__file__).resolve().parents[2]
# How long the API has to come up, and how long it has to stop when asked before it is forced.
READY_S = 30.0
STOP_S = 10.0


class ServerDidNotStart(RuntimeError):
    """The test API did not come up. The message says why and where its log is."""


def server_env(*, model: str | None, free: bool) -> dict[str, str]:
    """This process's environment with the copy database, demo sign-in on and cookies that work
    over plain http, and with the model when one is given. Free mode runs the scripted demo
    agent; a paid run drops any choice of agent it inherited, so the app's own .env decides, as
    on the live site. Refused, by the guard, when the database would not be the copy."""
    env = dict(os.environ)
    env["DATABASE_URL"] = copy_database_url()
    env["DEMO_SIGN_IN"] = "true"
    env["COOKIE_SECURE"] = "false"
    if model:
        env["OPENROUTER_MODEL"] = model
    if free:
        env["AGENT_CLIENT"] = "scripted"
    else:
        env.pop("AGENT_CLIENT", None)
    return env


@contextmanager
def test_server(
    *, model: str | None, free: bool, folder: Path, port: int = TEST_PORT
) -> Iterator[str]:
    """Runs the test API for the length of the `with` block and yields its address.

    Refused before anything starts when the address or the database is not the test copy's, or
    when something already listens on the port (an API left from before would answer in this
    one's place). Waits up to 30 s for the API to answer with demo sign-in on, and always stops
    it, on an error or Ctrl-C too. Its output goes to server.log in `folder`, the run's folder.
    """
    base_url = f"http://{LOCAL_HOST}:{port}"
    check_target(base_url)
    env = server_env(model=model, free=free)
    if _taken(port):
        raise Refused(
            f"Something is already listening on {LOCAL_HOST}:{port}. Stop it first, so that the "
            "run talks to an API of its own."
        )
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "server.log"
    with log.open("ab") as out:
        process = subprocess.Popen(
            ["uv", "run", "uvicorn", "app.main:app", "--host", LOCAL_HOST, "--port", str(port)],
            cwd=BACKEND,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            # A process group of its own, so that stopping the group stops uvicorn as well as uv.
            start_new_session=True,
        )
        # Straight after the start, so that nothing, Ctrl-C included, comes between the start
        # and the promise to stop.
        try:
            _wait_until_ready(process, base_url, log)
            yield base_url
        finally:
            _stop(process)


# Its name starts with test_, so pytest would take it for a test in any test module that imports
# it by name.
test_server.__test__ = False


def _taken(port: int) -> bool:
    """Whether something already answers on this machine's port."""
    try:
        with socket.create_connection((LOCAL_HOST, port), timeout=1):
            return True
    except OSError:
        return False


def _ready(base_url: str) -> bool:
    """Whether the API answers and says demo sign-in is on: the sign that it started with the
    run's settings."""
    try:
        reply = httpx.get(f"{base_url}/api/auth/config", timeout=2)
        body = reply.json()
    except (httpx.HTTPError, ValueError):
        return False
    return reply.status_code == 200 and isinstance(body, dict) and body.get("demo_sign_in") is True


def _wait_until_ready(process: subprocess.Popen, base_url: str, log: Path) -> None:
    """Asks every half second until the API is up. Fails at once if it has exited, and after
    30 s if it has not come up."""
    deadline = monotonic() + READY_S
    while True:
        if process.poll() is not None:
            raise ServerDidNotStart(
                f"The test API stopped before it was up (exit code {process.returncode}). "
                f"Its log is {log}."
            )
        if _ready(base_url):
            return
        if monotonic() >= deadline:
            raise ServerDidNotStart(
                f"The test API was not up within {READY_S:.0f} s. Its log is {log}."
            )
        sleep(0.5)


def _stop(process: subprocess.Popen) -> None:
    """Stops the API's process group: asks it to stop, and kills it if uv is still running 10 s
    later. uv waits for the uvicorn it started, so once uv has gone, both have."""
    _signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=STOP_S)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        process.wait()


def _signal_group(process: subprocess.Popen, sig: signal.Signals) -> None:
    """Sends `sig` to the API's process group. uv leads the group, so its id is uv's pid."""
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        # Nothing is left to stop. The group has gone, or holds only uv's exit, not yet
        # collected, which macOS answers with a permission error.
        return
