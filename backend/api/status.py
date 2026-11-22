"""Is everything working? One cheap call for the website's status page."""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.config import get_settings
from backend.database.connection import get_engine
from backend.schemas.status import StatusResponse
from backend.services.status_service import StatusService

router = APIRouter(tags=["health"])


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    """Each part of the platform with ok / warning / failed and when it last worked:
    database, prices, news, BSE filings, AI, and the daily and hourly runs.

    Read from the database only, so it never spends outside API quotas.
    """
    return StatusResponse(**StatusService(get_engine(), get_settings()).report())
