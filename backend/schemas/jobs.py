"""Response schemas for collection jobs (refreshes and scheduled runs)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

JobStatus = Literal["pending", "running", "completed", "completed_with_errors", "failed"]


class JobStep(BaseModel):
    status: Literal["running", "completed", "completed_with_errors", "failed", "skipped"]
    detail: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    job_id: UUID
    job_type: Literal["company_refresh", "scheduled_run", "feeds_run"]
    company_id: UUID | None = None
    company_name: str | None = None
    triggered_by: Literal["api", "schedule", "manual"]
    status: JobStatus
    steps: dict[str, JobStep] = Field(default_factory=dict, description="In the order they ran")
    error: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RefreshResponse(Job):
    created: bool = Field(..., description="False when an active or very recent refresh was returned instead")
    poll_url: str


class JobListResponse(BaseModel):
    company_id: UUID
    company_name: str
    count: int
    jobs: list[Job]
