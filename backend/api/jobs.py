"""Job status: what a refresh or scheduled run is doing, step by step."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.database.connection import get_engine
from backend.schemas.errors import ErrorResponse
from backend.schemas.jobs import Job
from backend.services.pipeline import JobLimits, JobService, default_steps

router = APIRouter(prefix="/jobs", tags=["jobs"])


@lru_cache
def _service() -> JobService:
    settings = get_settings()
    engine = get_engine()
    return JobService(engine, default_steps(engine, settings), JobLimits.from_settings(settings))


def get_job_service() -> JobService:
    """FastAPI dependency (overridden in tests)."""
    return _service()


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


@router.get("/{job_id}", response_model=Job,
            responses={404: {"model": ErrorResponse, "description": "Not found"}})
def get_job(job_id: UUID, service: JobServiceDep) -> Job:
    """Poll this after `POST /stocks/{ticker}/refresh` until `status` is no longer pending or running."""
    job = service.get(job_id)
    if job is None:
        raise NotFoundError(f"No job with id {job_id}.")
    return Job(**job)
