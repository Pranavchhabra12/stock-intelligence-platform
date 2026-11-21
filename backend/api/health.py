"""Liveness and database connectivity check."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.core.errors import ServiceUnavailableError
from backend.database.connection import get_engine
from backend.database.repositories import CompanyRepository

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict[str, str]:
    try:
        with get_engine().connect() as conn:
            CompanyRepository(conn).ping()
    except Exception:  # noqa: BLE001 - any failure means "not healthy"
        logger.exception("health_check_failed")
        raise ServiceUnavailableError("Database is unreachable.") from None
    return {"status": "ok", "database": "ok"}
