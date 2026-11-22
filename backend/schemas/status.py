"""System status response."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

State = Literal["ok", "warning", "failed"]


class StatusCheck(BaseModel):
    name: str
    status: State
    detail: str
    last_success: datetime | None = None


class ApiInfo(BaseModel):
    version: str = Field(..., description="Deployed commit")
    started_at: datetime
    region: str | None = None


class CompanyCounts(BaseModel):
    listed: int | None = None
    tracked: int | None = None
    cap: int


class StatusResponse(BaseModel):
    status: State = Field(..., description="The worst of the checks")
    checked_at: datetime
    api: ApiInfo
    database_ms: int | None = None
    companies: CompanyCounts
    checks: list[StatusCheck]
