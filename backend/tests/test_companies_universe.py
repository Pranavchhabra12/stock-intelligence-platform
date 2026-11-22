"""The full NSE company list, tracking ("Add to Power BI") and the one-call company page."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from backend.api.jobs import get_job_service
from backend.database.load_universe import load, parse, short_name
from backend.services.company_matcher import CompanyMatcher
from backend.services.pipeline import JobLimits, JobService
from backend.services.tracking_service import LimitReachedError, TrackingService
from backend.tests.test_pipeline import FakeSteps

HEADER = "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"


def csv_rows(n: int = 120) -> str:
    lines = [f"ZZTEST{i},Zeta Test Industries {i} Limited,EQ,01-JAN-2000,10,1,INE{i:05d}A01{i % 10},10"
             for i in range(n)]
    lines.append("INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5")   # already in the database
    lines.append("BAD SYMBOL,Broken Row Limited,EQ,01-JAN-2000,10,1,NOTANISIN,10")  # skipped
    return HEADER + "\n".join(lines) + "\n"


def remove_universe(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("delete from app.collection_jobs"))
        ids = "select company_id from app.companies where company_name like 'Zeta Test Industries%'"
        conn.execute(text(f"delete from app.company_listings where company_id in ({ids})"))
        conn.execute(text("delete from app.companies where company_name like 'Zeta Test Industries%'"))


@pytest.fixture
def universe(engine: Engine) -> Iterator[None]:
    remove_universe(engine)
    load(engine, parse(csv_rows()))
    yield
    remove_universe(engine)


def test_parse_and_names() -> None:
    rows = parse(csv_rows(3) + "")
    assert [r["symbol"] for r in rows] == ["ZZTEST0", "ZZTEST1", "ZZTEST2", "INFY"]
    assert rows[0]["name"] == "Zeta Test Industries 0" and rows[0]["legal"] == "Zeta Test Industries 0 Limited"
    assert short_name("Tata Motors Ltd.") == "Tata Motors" and short_name("Limited") == "Limited"


def test_load_adds_new_companies_untracked_and_is_repeatable(engine: Engine, universe: None) -> None:
    with engine.connect() as conn:
        added = conn.execute(text("select count(*), bool_or(is_tracked) from app.companies "
                                  "where company_name like 'Zeta Test Industries%'")).one()
    assert added == (120, False)
    again = load(engine, parse(csv_rows()))
    assert again["companies_added"] == 0                 # nothing duplicated
    with pytest.raises(ValueError):
        load(engine, parse(csv_rows(10)))                # a short download is refused


def test_search_finds_untracked_companies_and_marks_tracking(client: TestClient, universe: None) -> None:
    hits = client.get("/stocks/search", params={"q": "zeta test industries 7"}).json()["results"]
    assert hits[0]["company_name"] == "Zeta Test Industries 7" and hits[0]["is_tracked"] is False
    infy = client.get("/stocks/search", params={"q": "INFY"}).json()["results"][0]
    assert infy["is_tracked"] is True
    detail = client.get("/stocks/ZZTEST7").json()
    assert detail["is_tracked"] is False and detail["listings"][0]["isin"].startswith("INE")


def test_daily_jobs_and_news_matching_skip_untracked_companies(engine: Engine, universe: None) -> None:
    with engine.connect() as conn:
        zeta = conn.execute(text("select company_id from app.companies where company_name = 'Zeta Test Industries 3'")
                            ).scalar_one()
        matcher = CompanyMatcher.from_database(conn)
        with_zeta = CompanyMatcher.from_database(conn, [zeta])
    assert not matcher.match("Zeta Test Industries 3 wins a large order")
    assert with_zeta.match("Zeta Test Industries 3 wins a large order")[0].company_id == zeta


def test_tracking_cap_and_idempotence(engine: Engine, universe: None) -> None:
    with engine.connect() as conn:
        ids = conn.execute(text("select company_id from app.companies where company_name like 'Zeta Test%' "
                                "order by company_name limit 3")).scalars().all()
    service = TrackingService(engine, cap=7)     # 5 seeded + 2 more
    assert service.track(ids[0]) == (True, 6)
    assert service.track(ids[0]) == (False, 6)   # already tracked
    assert service.track(ids[1]) == (True, 7)
    with pytest.raises(LimitReachedError) as err:
        service.track(ids[2])
    assert err.value.details == {"tracked": 7, "cap": 7}
    with engine.connect() as conn:
        via = conn.execute(text("select tracked_via from app.companies where company_id = :i"), {"i": ids[0]}).scalar()
    assert via == "visitor"


@pytest.fixture
def fake_jobs(client: TestClient, engine: Engine) -> Iterator[FakeSteps]:
    steps = FakeSteps()
    client.app.dependency_overrides[get_job_service] = lambda: JobService(engine, steps, JobLimits())
    yield steps
    client.app.dependency_overrides.pop(get_job_service, None)


def test_track_api_starts_a_full_refresh(client: TestClient, universe: None, fake_jobs: FakeSteps) -> None:
    first = client.post("/stocks/ZZTEST9/track")
    assert first.status_code == 200
    body = first.json()
    assert body["created"] and body["is_tracked"] and body["tracked_count"] == 6 and body["cap"] == 25
    assert body["job_id"] and [c[0] for c in fake_jobs.calls] == ["prices", "news", "documents", "analysis"]
    again = client.post("/stocks/ZZTEST9/track").json()
    assert again["created"] is False and again["job_id"] is None
    names = [c["company_name"] for c in client.get("/stocks").json()["companies"]]
    assert "Zeta Test Industries 9" in names     # now on the home page and in Power BI
    assert client.post("/stocks/NOPE/track").status_code == 404


def test_company_page_in_one_request(client: TestClient, universe: None) -> None:
    page = client.get("/stocks/INFY/page").json()
    assert page["company"]["company_name"] == "Infosys" and page["company"]["is_tracked"] is True
    assert set(page) >= {"summary", "prices", "quarterly", "annual", "news", "sentiment", "analysis", "reports"}
    assert page["tracking"] == {"tracked_count": 5, "cap": 25} and page["missing"] == []
    new = client.get("/stocks/ZZTEST4/page").json()
    assert new["company"]["is_tracked"] is False and new["summary"]["price"] is None
    assert client.get("/stocks/NOPE/page").status_code == 404


def test_ai_is_skipped_for_untracked_companies(engine: Engine, universe: None, database_url: str) -> None:
    from backend.core.config import Settings
    from backend.services.pipeline import default_steps

    with engine.connect() as conn:
        zeta = conn.execute(text("select company_id from app.companies where company_name = 'Zeta Test Industries 2'")
                            ).scalar_one()
    settings = Settings(_env_file=None, database_url=database_url, gemini_api_key="not-used")
    status, detail = default_steps(engine, settings)["analysis"]([zeta])
    assert status == "skipped" and "added to Power BI" in detail["reason"]
