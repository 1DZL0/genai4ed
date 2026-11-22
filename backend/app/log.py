"""Application logging: plain lines on stdout (`docker compose logs api`), so the first
question after a bad lesson, "what happened at 10:14", has an answer. Two loggers:
`pact.model` for every model call (purpose, model, status, latency) and `pact.http`
for requests that failed on the server or ran slow. No line carries what anyone wrote."""

import logging
import os

MODEL = logging.getLogger("pact.model")
HTTP = logging.getLogger("pact.http")

_configured = False


def configure_logging() -> None:
    """Once per process. LOG_LEVEL in the environment (INFO by default) sets the level."""
    global _configured
    if _configured:
        return
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # Uvicorn's access log repeats every poll; the lines here say what mattered.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True
