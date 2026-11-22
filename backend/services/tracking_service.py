"""Adding a company to Power BI: from then on it is collected every day, analysed by AI and
included in the dashboard data. Anyone can add one, up to a cap that protects the free tiers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Engine, text

from backend.core.errors import AppError

# Serialises adds so two visitors can't both take the last free place.
_TRACK_LOCK = 81_120_001


class LimitReachedError(AppError):
    status_code = 409
    code = "limit_reached"


class TrackingService:
    def __init__(self, engine: Engine, cap: int) -> None:
        self.engine = engine
        self.cap = cap

    def count(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text("select count(*) from app.companies where is_tracked")).scalar_one()

    def track(self, company_id: UUID, via: str = "visitor") -> tuple[bool, int]:
        """Returns (newly added, companies tracked now). Adding one already tracked is a no-op."""
        with self.engine.begin() as conn:
            conn.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _TRACK_LOCK})
            already = conn.execute(text("select is_tracked from app.companies where company_id = :id"),
                                   {"id": company_id}).scalar_one()
            count = conn.execute(text("select count(*) from app.companies where is_tracked")).scalar_one()
            if already:
                return False, count
            if count >= self.cap:
                raise LimitReachedError(
                    f"Power BI already follows {count} companies, the most this free demo allows.",
                    {"tracked": count, "cap": self.cap})
            conn.execute(text(
                "update app.companies set is_tracked = true, tracked_at = now(), tracked_via = :via "
                "where company_id = :id"), {"id": company_id, "via": via})
            return True, count + 1
