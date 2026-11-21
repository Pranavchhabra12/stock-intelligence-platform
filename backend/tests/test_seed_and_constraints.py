"""Seed idempotency and the database constraints that prevent duplicates."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from backend.database.seed import seed
from backend.tests.conftest import SEED_FILE

SEED = json.loads(SEED_FILE.read_text(encoding="utf-8"))


def test_seed_is_idempotent(db: Connection) -> None:
    first = seed(db, SEED)
    second = seed(db, SEED)
    assert first == second
    assert first["companies"] == 5
    assert first["listings"] == 10


def test_each_company_has_one_nse_and_one_bse_listing(db: Connection) -> None:
    rows = db.execute(
        text(
            """
            select c.company_name,
                   count(*) filter (where l.exchange = 'NSE') as nse,
                   count(*) filter (where l.exchange = 'BSE') as bse
            from app.companies c join app.company_listings l using (company_id)
            group by c.company_name
            """
        )
    ).all()
    assert len(rows) == 5
    assert all(r.nse == 1 and r.bse == 1 for r in rows)


def _company_id(db: Connection) -> object:
    return db.execute(text("select company_id from app.companies limit 1")).scalar_one()


def test_duplicate_active_listing_is_rejected(db: Connection) -> None:
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "insert into app.company_listings (company_id, exchange, symbol) "
                "values (:id, 'NSE', 'RELIANCE')"
            ),
            {"id": _company_id(db)},
        )


def test_inactive_listing_frees_the_symbol(db: Connection) -> None:
    db.execute(text("update app.company_listings set is_active = false where symbol = 'INFY'"))
    db.execute(
        text(
            "insert into app.company_listings (company_id, exchange, symbol) "
            "values (:id, 'NSE', 'INFY')"
        ),
        {"id": _company_id(db)},
    )


@pytest.mark.parametrize(
    ("column", "value"),
    [("isin", "US0378331005"), ("isin", "INE002A0101X"), ("symbol", "reliance2")],
)
def test_listing_format_checks(db: Connection, column: str, value: str) -> None:
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                f"insert into app.company_listings (company_id, exchange, symbol, {column}) "
                f"values (:id, 'NSE', 'TESTSYM', :v)"
                if column != "symbol"
                else "insert into app.company_listings (company_id, exchange, symbol) "
                "values (:id, 'NSE', :v)"
            ),
            {"id": _company_id(db), "v": value},
        )


def test_cin_format_check(db: Connection) -> None:
    with pytest.raises(IntegrityError):
        db.execute(text("insert into app.companies (company_name, cin) values ('X', 'BAD-CIN')"))


def test_alias_duplicates_collapse_on_normalised_form(db: Connection) -> None:
    company_id = _company_id(db)
    db.execute(
        text("insert into app.company_aliases (company_id, alias, alias_type) "
             "values (:id, 'Some Name', 'name')"),
        {"id": company_id},
    )
    with pytest.raises(IntegrityError):
        db.execute(
            text("insert into app.company_aliases (company_id, alias, alias_type) "
                 "values (:id, 'some-name!', 'name')"),
            {"id": company_id},
        )
