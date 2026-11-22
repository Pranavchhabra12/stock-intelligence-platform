"""FastAPI application entry point.

Run locally:  uvicorn backend.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import health, jobs, status, stocks
from backend.core.config import get_settings
from backend.core.errors import register_error_handlers
from backend.core.logging import configure_logging
from backend.core.middleware import install_middleware

DISCLAIMER = (
    "Educational research project. Not investment advice. "
    "Market data is delayed and comes from third-party sources."
)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Stock Intelligence Platform API",
        version="0.1.0",
        description=f"Research API for Indian listed companies (NSE/BSE). {DISCLAIMER}",
    )
    install_middleware(app, settings.api_rate_limit_per_minute,
                       settings.internal_api_key.get_secret_value() if settings.internal_api_key else None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(stocks.router)
    app.include_router(jobs.router)

    from backend.core.bse_probe import maybe_start

    maybe_start()   # one-off BSE reachability check, only with PROBE_BSE=1
    return app


app = create_app()
