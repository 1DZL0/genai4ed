"""The guards a school day keeps to: it runs on the test copy, never the live site, and never
spends the key below the floor.

The run drives a test API on this machine (127.0.0.1, port 8010 unless told otherwise) that is
backed by the copy database, genai4ed_memory. The live site's API is on port 8000 and its
website on 3000, over the database genai4ed. So the run refuses any address but a test one on
this machine, and any database but the copy on this machine's Postgres.

The key is shared with the live site. Before each paid part the runner reads what is left on it
and stops if the part would take it below the floor: $15 unless it is told otherwise.

The database URL holds a password and the key is a secret: neither is printed, logged, saved or
put in a message, and a refusal says what is wrong in words.
"""

from urllib.parse import urlsplit

import httpx
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.config import get_settings

COPY_DATABASE = "genai4ed_memory"
TEST_PORT = 8010
FLOOR = 15.0

LOCAL_HOST = "127.0.0.1"
# How the copy's URL ends: this machine's Postgres, where the live database is too.
COPY_ENDING = f"@{LOCAL_HOST}:5433/{COPY_DATABASE}"
LIVE_PORTS = {8000: "the live site's API", 3000: "the live site's website"}
KEY_URL = "https://openrouter.ai/api/v1/key"


class Refused(Exception):
    """The run would touch the live site or a database other than the copy, or spend below the
    floor. The message says why in words; it never holds the database URL or the key."""


def copy_database_url() -> str:
    """The app's database URL with only the database name changed to the copy's. Refused unless
    the result is the copy on this machine's Postgres."""
    try:
        url = make_url(get_settings().database_url).set(database=COPY_DATABASE)
    except (ArgumentError, ValueError):
        # The parser's own message can quote part of the password, so it goes no further: the
        # refusal is raised out here, with nothing chained to it.
        url = None
    if url is None:
        raise Refused("The database URL in the settings can't be read, so the copy can't be found.")
    copy = url.render_as_string(hide_password=False)
    # The host must be this machine; the ending also pins the port and the name, and leaves no
    # room for a query that could send the connection somewhere else.
    if url.host != LOCAL_HOST or not copy.endswith(COPY_ENDING):
        raise Refused(
            f"The database would not be the copy ({COPY_DATABASE} on this machine's Postgres), "
            "so the run will not start."
        )
    return copy


def check_target(base_url: str) -> None:
    """Refuses any API but a test one on this machine: the host must be 127.0.0.1 and the port
    must be named, and be neither the live site's API (8000) nor its website (3000)."""
    parts = urlsplit(base_url)
    try:
        port = parts.port
    except ValueError:
        # A port that is not a number names no port at all.
        port = None
    if parts.hostname != LOCAL_HOST:
        raise Refused(f"The run only talks to a test API on this machine ({LOCAL_HOST}).")
    if port is None:
        raise Refused("The test API's address must name its port.")
    if port in LIVE_PORTS:
        raise Refused(f"Port {port} is {LIVE_PORTS[port]}; the run only talks to a test API.")


async def remaining() -> float:
    """The dollars left on the key's limit, as OpenRouter reports them. Refused when there is no
    key, OpenRouter can't be reached or turns the key down, or the key has no limit: the floor
    can only be kept when what is left is known. The key goes in the request's header and
    nowhere else."""
    key = get_settings().openrouter_api_key
    if not key:
        raise Refused("There is no OpenRouter key in the settings, so what is left can't be read.")
    left = problem = None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            reply = await client.get(KEY_URL, headers={"Authorization": f"Bearer {key}"})
        reply.raise_for_status()
        left = reply.json()["data"]["limit_remaining"]
        left = None if left is None else float(left)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        problem = f"OpenRouter answered {status} when asked what is left on the key."
    except httpx.HTTPError as e:
        problem = f"OpenRouter could not be asked what is left on the key ({type(e).__name__})."
    except (ValueError, KeyError, TypeError):
        problem = "OpenRouter's answer did not say what is left on the key."
    # Raised out here so that nothing is chained to the refusal: the failed request still holds
    # the key in its header.
    if problem:
        raise Refused(problem)
    if left is None:
        raise Refused("The key has no spending limit, so what is left can't be held to the floor.")
    return left


def affordable(estimate: float, left: float, floor: float = FLOOR) -> bool:
    """Whether a part costing about `estimate` dollars still leaves `floor` on the key."""
    return left - estimate >= floor
