import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import get_sessionmaker
from app.log import HTTP, configure_logging
from app.routers import account, learn, lessons, research, teacher, thread

# A request slower than this is worth a line even when it succeeded.
SLOW_SECONDS = 10.0


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="GenAI4ED",
        description=("A teacher-governed class agent. Internal prototype - not for student use."),
        version="0.1.0",
    )

    @app.middleware("http")
    async def log_failures(request: Request, call_next):
        """One line for a request that failed on the server or ran slow: method, path,
        status, milliseconds. Never the body, never a query string."""
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            ms = int((time.perf_counter() - started) * 1000)
            HTTP.exception("%s %s 500 %dms", request.method, request.url.path, ms)
            raise
        ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 500:
            HTTP.error("%s %s %d %dms", request.method, request.url.path, response.status_code, ms)
        elif ms >= SLOW_SECONDS * 1000:
            HTTP.warning(
                "%s %s %d %dms slow", request.method, request.url.path, response.status_code, ms
            )
        return response
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(account.router)
    app.include_router(lessons.router)
    app.include_router(learn.router)
    app.include_router(thread.router)
    app.include_router(teacher.router)
    app.include_router(research.router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Liveness. Deliberately touches nothing."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        """Readiness. 503 while the database is unreachable."""
        try:
            async with get_sessionmaker()() as session:
                await session.execute(text("select 1"))
        except Exception as exc:  # noqa: BLE001 - reported, not raised, to the probe
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "database": "unavailable", "detail": str(exc)},
            )
        return JSONResponse(content={"status": "ok", "database": "ok"})

    return app


app = create_app()
