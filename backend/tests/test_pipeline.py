"""Phase 5: jobs, the refresh endpoint, and the schedules."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from backend.api.jobs import get_job_service
from backend.core.config import Settings
from backend.services.pipeline import JobLimits, JobService, TooBusyError, default_steps, overall_status


@pytest.fixture
def clean(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("delete from app.collection_jobs"))
    yield
    with engine.begin() as conn:
        conn.execute(text("delete from app.collection_jobs"))


def company_id(engine: Engine, name: str = "Infosys") -> UUID:
    with engine.connect() as conn:
        return conn.execute(text("select company_id from app.companies where company_name = :n"),
                            {"n": name}).scalar_one()


class FakeSteps(dict):
    """Steps that record their calls; `fail` makes a step crash, `partial` makes it report errors."""

    def __init__(self, fail: set[str] = frozenset(), partial: set[str] = frozenset()) -> None:
        self.calls: list[tuple[str, list | None]] = []
        for name in ("prices", "news", "documents", "analysis"):
            self[name] = self._make(name, fail, partial)

    def _make(self, name: str, fail: set[str], partial: set[str]):  # noqa: ANN202
        def step(ids):  # noqa: ANN001, ANN202
            self.calls.append((name, ids))
            if name in fail:
                raise RuntimeError(f"{name} provider is down")
            if name in partial:
                return "completed_with_errors", {"errors": [f"{name}: one source failed"], "items": 3}
            return "completed", {"items": 5}
        return step


def service(engine: Engine, steps: dict | None = None, **limits) -> JobService:  # noqa: ANN003
    return JobService(engine, steps if steps is not None else FakeSteps(), JobLimits(**limits))


def test_overall_status() -> None:
    assert overall_status(["completed", "skipped"]) == "completed"
    assert overall_status(["completed", "failed"]) == "completed_with_errors"
    assert overall_status(["failed", "failed", "skipped"]) == "failed"
    assert overall_status(["skipped"]) == "completed"


def test_refresh_runs_every_step_for_the_company(engine: Engine, clean: None) -> None:
    steps = FakeSteps()
    jobs = service(engine, steps)
    cid = company_id(engine)
    job, created = jobs.request_refresh(cid)
    assert created and job["status"] == "pending" and job["company_name"] == "Infosys"

    done = jobs.run(job["job_id"])
    assert [c[0] for c in steps.calls] == ["prices", "news", "documents", "analysis"]
    assert all(ids == [cid] for _, ids in steps.calls)
    assert done["status"] == "completed" and done["error"] is None
    assert list(done["steps"]) == ["prices", "news", "documents", "analysis"]
    assert done["steps"]["news"] == {"status": "completed", "detail": {"items": 5}}
    assert done["started_at"] >= done["requested_at"] and done["finished_at"] >= done["started_at"]
    assert jobs.run(job["job_id"]) is None   # can't run twice


def test_a_crashing_step_does_not_stop_the_others(engine: Engine, clean: None) -> None:
    steps = FakeSteps(fail={"prices"}, partial={"news"})
    jobs = service(engine, steps)
    job, _ = jobs.request_refresh(company_id(engine))
    done = jobs.run(job["job_id"])
    assert [c[0] for c in steps.calls] == ["prices", "news", "documents", "analysis"]
    assert done["status"] == "completed_with_errors"
    assert done["steps"]["prices"]["status"] == "failed"
    assert "RuntimeError: prices provider is down" in done["steps"]["prices"]["detail"]["errors"][0]
    assert "prices: RuntimeError" in done["error"] and "news: news: one source failed" in done["error"]

    all_fail = service(engine, FakeSteps(fail={"prices", "news", "documents", "analysis"}))
    job, _ = all_fail.request_refresh(company_id(engine, "Tata Consultancy Services"))
    assert all_fail.run(job["job_id"])["status"] == "failed"


def test_one_active_refresh_per_company_and_a_cooldown(engine: Engine, clean: None) -> None:
    jobs = service(engine)
    cid = company_id(engine)
    first, created = jobs.request_refresh(cid)
    again, created_again = jobs.request_refresh(cid)
    assert created and not created_again and again["job_id"] == first["job_id"]   # still pending

    jobs.run(first["job_id"])
    recent, created_recent = jobs.request_refresh(cid)
    assert not created_recent and recent["job_id"] == first["job_id"] and recent["status"] == "completed"

    no_cooldown = service(engine, cooldown=timedelta(0))
    fresh, created_fresh = no_cooldown.request_refresh(cid)
    assert created_fresh and fresh["job_id"] != first["job_id"]
    assert [j["job_id"] for j in jobs.recent(cid)] == [fresh["job_id"], first["job_id"]]


def test_failed_refreshes_can_be_retried_at_once(engine: Engine, clean: None) -> None:
    jobs = service(engine, FakeSteps(fail={"prices", "news", "documents", "analysis"}))
    cid = company_id(engine)
    job, _ = jobs.request_refresh(cid)
    jobs.run(job["job_id"])
    retry, created = jobs.request_refresh(cid)
    assert created and retry["job_id"] != job["job_id"]   # a failure doesn't trigger the cooldown


def test_too_many_active_jobs(engine: Engine, clean: None) -> None:
    jobs = service(engine, max_active=2)
    jobs.request_refresh(company_id(engine, "Infosys"))
    jobs.request_refresh(company_id(engine, "HDFC Bank"))
    with pytest.raises(TooBusyError):
        jobs.request_refresh(company_id(engine, "ICICI Bank"))


def test_stuck_jobs_are_expired(engine: Engine, clean: None) -> None:
    jobs = service(engine)
    cid = company_id(engine)
    stuck, _ = jobs.request_refresh(cid)
    with engine.begin() as conn:
        conn.execute(text("update app.collection_jobs set status = 'running', "
                          "requested_at = now() - interval '2 hours', started_at = now() - interval '2 hours' "
                          "where job_id = :id"), {"id": stuck["job_id"]})
    fresh, created = jobs.request_refresh(cid)
    assert created and fresh["job_id"] != stuck["job_id"]
    old = jobs.get(stuck["job_id"])
    assert old["status"] == "failed" and "restarted" in old["error"]


def test_runs_over_all_companies_never_overlap(engine: Engine, clean: None) -> None:
    steps = FakeSteps()
    jobs = service(engine, steps)
    run_id = jobs.create_run("feeds_run", "schedule")
    assert run_id is not None and jobs.create_run("feeds_run", "schedule") is None
    assert jobs.create_run("scheduled_run", "manual") is not None   # a different kind may run alongside
    done = jobs.run(run_id)
    assert [c[0] for c in steps.calls] == ["news", "documents", "analysis"]   # feeds: no prices
    assert all(ids is None for _, ids in steps.calls)                        # every company
    assert done["company_id"] is None and done["triggered_by"] == "schedule"
    with pytest.raises(ValueError):
        jobs.create_run("company_refresh", "manual")


def test_database_guards(engine: Engine, clean: None) -> None:
    with pytest.raises(Exception), engine.begin() as conn:  # noqa: B017, PT011
        conn.execute(text("insert into app.collection_jobs (job_type, triggered_by) values ('company_refresh', 'api')"))
    with pytest.raises(Exception), engine.begin() as conn:  # noqa: B017, PT011
        conn.execute(text("insert into app.collection_jobs (job_type, triggered_by, status) "
                          "values ('feeds_run', 'api', 'completed')"))   # finished without finished_at


def test_analysis_step_is_skipped_without_a_key(engine: Engine, database_url: str) -> None:
    settings = Settings(_env_file=None, database_url=database_url, gemini_api_key=None)
    status, detail = default_steps(engine, settings)["analysis"]([company_id(engine)])
    assert status == "skipped" and detail["reason"] == "GEMINI_API_KEY is not set"


# ---------------------------------------------------------------- API

@pytest.fixture
def fake_jobs(client: TestClient, engine: Engine, clean: None) -> Iterator[FakeSteps]:
    steps = FakeSteps(partial={"news"})
    client.app.dependency_overrides[get_job_service] = lambda: service(engine, steps)
    yield steps
    client.app.dependency_overrides.pop(get_job_service, None)


def test_refresh_api(client: TestClient, fake_jobs: FakeSteps) -> None:
    response = client.post("/stocks/INFY/refresh")
    assert response.status_code == 202
    body = response.json()
    assert body["created"] and body["company_name"] == "Infosys" and body["poll_url"] == f"/jobs/{body['job_id']}"

    # TestClient runs background tasks before returning, so the job has finished.
    job = client.get(body["poll_url"]).json()
    assert job["status"] == "completed_with_errors"
    assert [s["status"] for s in job["steps"].values()] == ["completed", "completed_with_errors", "completed",
                                                             "completed"]

    again = client.post("/stocks/INFY/refresh")
    assert again.status_code == 200 and not again.json()["created"] and again.json()["job_id"] == body["job_id"]

    history = client.get("/stocks/INFY/jobs").json()
    assert history["count"] == 1 and history["jobs"][0]["job_id"] == body["job_id"]


def test_refresh_api_errors(client: TestClient, engine: Engine, fake_jobs: FakeSteps) -> None:
    assert client.post("/stocks/NOPE/refresh").status_code == 404
    assert client.get("/jobs/00000000-0000-0000-0000-000000000001").status_code == 404
    assert client.get("/jobs/not-a-uuid").status_code == 422
    assert client.get("/stocks/INFY/refresh").status_code == 405

    client.app.dependency_overrides[get_job_service] = lambda: service(engine, FakeSteps(), max_active=1)
    with engine.begin() as conn:
        conn.execute(text("insert into app.collection_jobs (job_type, triggered_by) values ('feeds_run', 'schedule')"))
    busy = client.post("/stocks/TCS/refresh")
    assert busy.status_code == 429 and busy.json()["error"]["code"] == "busy"


# ---------------------------------------------------------------- schedules

def test_local_schedule() -> None:
    from backend.scheduler.local import build_scheduler

    jobs = {j.id: j for j in build_scheduler().get_jobs()}
    assert set(jobs) == {"daily_run", "feeds_run"}
    assert "hour='19', minute='30'" in str(jobs["daily_run"].trigger)
    assert jobs["feeds_run"].kwargs["argv"][0] == "--feeds"


def test_run_once_command(engine: Engine, clean: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.scheduler import run_once

    steps = FakeSteps()
    monkeypatch.setattr(run_once, "default_steps", lambda *a, **k: steps)
    assert run_once.main(["--feeds"]) == 0
    assert run_once.main(["INFY", "TCS"]) == 0
    assert run_once.main(["NOPE"]) == 1
    with engine.connect() as conn:
        rows = conn.execute(text("select job_type, triggered_by, status from app.collection_jobs "
                                 "order by requested_at")).all()
    assert [tuple(r) for r in rows] == [("feeds_run", "manual", "completed"),
                                        ("company_refresh", "manual", "completed"),
                                        ("company_refresh", "manual", "completed")]
