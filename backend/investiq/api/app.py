"""FastAPI application: local-only JSON API used by the dashboard (via its server-side proxy)."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from investiq import __version__
from investiq.api.deps import require_token
from investiq.api.routes import (
    ai_costs,
    brokerage,
    holdings,
    instruments,
    learning,
    news,
    notifications,
    paper,
    research,
    settings_routes,
    system,
    watchlists,
)
from investiq.config import get_settings

log = logging.getLogger(__name__)


def create_app(start_scheduler: bool | None = None) -> FastAPI:
    settings = get_settings()
    run_scheduler = settings.scheduler_enabled if start_scheduler is None else start_scheduler

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.scheduler = None
        if run_scheduler:
            from investiq.services.jobs import Scheduler

            app.state.scheduler = Scheduler(settings.scheduler_poll_seconds)
            app.state.scheduler.start()
            log.info("in-process scheduler started (poll %ss)", settings.scheduler_poll_seconds)
        yield
        if app.state.scheduler is not None:
            app.state.scheduler.stop()

    app = FastAPI(title="InvestIQ local API", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs" if not settings.is_production else None, redoc_url=None,
                  openapi_url="/api/openapi.json" if not settings.is_production else None)
    app.state.scheduler = None
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "::1", "testserver"])
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Authorization", "Content-Type",
                                                                                   "X-InvestIQ-Token"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Details go to the local log only; the response never includes internals or secrets.
        error_id = uuid.uuid4().hex[:12]
        log.exception("unhandled error %s on %s %s", error_id, request.method, request.url.path)
        return JSONResponse({"detail": "Internal error. See the InvestIQ log for details.", "error_id": error_id},
                            status_code=500)

    @app.get("/api/health", tags=["system"])
    def health_ping() -> dict:
        return {"ok": True, "version": __version__}

    protected = [Depends(require_token)]
    for module in (system, instruments, research, news, paper, learning, watchlists, notifications, ai_costs,
                   settings_routes, holdings, brokerage):
        app.include_router(module.router, prefix="/api", dependencies=protected)
    return app
