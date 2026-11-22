"""Idempotent seed loader for master data.

Run:  python -m backend.database.seed [path/to/companies.json]

Safe to run any number of times: every write is an upsert, and companies are
matched through their listings (ISIN, then exchange + symbol), so the same
company is never inserted twice.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from backend.core.config import get_settings
from backend.core.logging import configure_logging

logger = logging.getLogger(__name__)

DEFAULT_SEED_FILE = Path(__file__).resolve().parents[2] / "database" / "seed" / "companies.json"

_SOURCE_FIELDS = (
    "source_name", "source_type", "base_url", "terms_url", "attribution_required",
    "attribution_text", "redistribution_allowed", "license_notes",
)


def upsert_data_source(conn: Connection, src: dict[str, Any]) -> int:
    values = {f: src.get(f) for f in _SOURCE_FIELDS}
    values["attribution_required"] = bool(values["attribution_required"])
    values["source_code"] = src["source_code"]
    return conn.execute(
        text(
            """
            insert into app.data_sources
              (source_code, source_name, source_type, base_url, terms_url,
               attribution_required, attribution_text, redistribution_allowed, license_notes)
            values
              (:source_code, :source_name, :source_type, :base_url, :terms_url,
               :attribution_required, :attribution_text, :redistribution_allowed, :license_notes)
            on conflict (source_code) do update set
              source_name = excluded.source_name,
              source_type = excluded.source_type,
              base_url = excluded.base_url,
              terms_url = excluded.terms_url,
              attribution_required = excluded.attribution_required,
              attribution_text = excluded.attribution_text,
              redistribution_allowed = excluded.redistribution_allowed,
              license_notes = excluded.license_notes
            returning source_id
            """
        ),
        values,
    ).scalar_one()


def _find_existing_company(conn: Connection, listings: list[dict[str, Any]]) -> UUID | None:
    for listing in listings:
        found = conn.execute(
            text(
                """
                select company_id from app.company_listings
                where is_active
                  and ((cast(:isin as text) is not null and isin = :isin)
                       or (exchange = :exchange and symbol = :symbol))
                limit 1
                """
            ),
            {"isin": listing.get("isin"), "exchange": listing["exchange"],
             "symbol": listing["symbol"].upper()},
        ).scalar()
        if found:
            return found
    return None


def upsert_company(conn: Connection, company: dict[str, Any], sources: dict[str, int]) -> UUID:
    listings = company["listings"]
    company_id = _find_existing_company(conn, listings)

    params = {
        "name": company["company_name"],
        "legal_name": company.get("legal_name"),
        "cin": company.get("cin"),
        "sector": company.get("sector"),
        "industry": company.get("industry"),
        "website": company.get("website"),
        "exclude": company.get("news_exclude_phrases", []),
    }
    if company_id is None:
        company_id = conn.execute(
            text(
                """
                insert into app.companies
                  (company_name, legal_name, cin, sector, industry, website, news_exclude_phrases)
                values (:name, :legal_name, :cin, :sector, :industry, :website, :exclude)
                returning company_id
                """
            ),
            params,
        ).scalar_one()
    else:
        # Never overwrite a known value with an empty one.
        conn.execute(
            text(
                """
                update app.companies set
                  company_name = :name,
                  legal_name = coalesce(:legal_name, legal_name),
                  cin = coalesce(:cin, cin),
                  sector = coalesce(:sector, sector),
                  industry = coalesce(:industry, industry),
                  website = coalesce(:website, website),
                  news_exclude_phrases = :exclude
                where company_id = :id
                """
            ),
            {**params, "id": company_id},
        )

    for listing in listings:
        listing_id = _upsert_listing(conn, company_id, listing)
        if listing.get("yfinance") and "yfinance" in sources:
            conn.execute(
                text(
                    """
                    insert into app.listing_provider_ids (listing_id, source_id, provider_symbol)
                    values (:listing_id, :source_id, :symbol)
                    on conflict (listing_id, source_id)
                      do update set provider_symbol = excluded.provider_symbol
                    """
                ),
                {"listing_id": listing_id, "source_id": sources["yfinance"],
                 "symbol": listing["yfinance"]},
            )

    aliases = [{"alias": company["company_name"], "alias_type": "name"}]
    if company.get("legal_name"):
        aliases.append({"alias": company["legal_name"], "alias_type": "legal_name"})
    aliases += company.get("aliases", [])
    aliases += [{"alias": lst["symbol"], "alias_type": "symbol"} for lst in listings]
    for alias in aliases:
        conn.execute(
            text(
                """
                insert into app.company_aliases (company_id, alias, alias_type)
                values (:company_id, :alias, :alias_type)
                on conflict (company_id, alias_norm) do nothing
                """
            ),
            {"company_id": company_id, **alias},
        )
    return company_id


def _upsert_listing(conn: Connection, company_id: UUID, listing: dict[str, Any]) -> UUID:
    params = {
        "company_id": company_id,
        "exchange": listing["exchange"],
        "symbol": listing["symbol"].upper(),
        "exchange_code": listing.get("exchange_code"),
        "isin": listing.get("isin"),
        "series": listing.get("series"),
    }
    existing = conn.execute(
        text(
            """
            select listing_id, company_id from app.company_listings
            where is_active and exchange = :exchange and symbol = :symbol
            """
        ),
        params,
    ).mappings().first()

    if existing is None:
        return conn.execute(
            text(
                """
                insert into app.company_listings
                  (company_id, exchange, symbol, exchange_code, isin, series)
                values (:company_id, :exchange, :symbol, :exchange_code, :isin, :series)
                returning listing_id
                """
            ),
            params,
        ).scalar_one()

    if existing["company_id"] != company_id:
        raise ValueError(
            f"{params['exchange']}:{params['symbol']} already belongs to another company; "
            "refusing to move it silently."
        )
    conn.execute(
        text(
            """
            update app.company_listings set
              exchange_code = coalesce(:exchange_code, exchange_code),
              isin = coalesce(:isin, isin),
              series = coalesce(:series, series)
            where listing_id = :listing_id
            """
        ),
        {**params, "listing_id": existing["listing_id"]},
    )
    return existing["listing_id"]


def seed(conn: Connection, data: dict[str, Any]) -> dict[str, int]:
    """Apply seed data inside the caller's transaction. Returns row counts."""
    sources = {s["source_code"]: upsert_data_source(conn, s) for s in data.get("data_sources", [])}
    for company in data.get("companies", []):
        upsert_company(conn, company, sources)

    counts = conn.execute(
        text(
            """
            select
              (select count(*) from app.data_sources)         as data_sources,
              (select count(*) from app.companies)            as companies,
              (select count(*) from app.company_listings)     as listings,
              (select count(*) from app.company_aliases)      as aliases,
              (select count(*) from app.listing_provider_ids) as provider_ids
            """
        )
    ).mappings().one()
    return dict(counts)


def main(argv: list[str]) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SEED_FILE
    data = json.loads(path.read_text(encoding="utf-8"))

    engine = create_engine(settings.sqlalchemy_database_url)
    with engine.begin() as conn:  # one transaction: all or nothing
        counts = seed(conn, data)
    engine.dispose()
    logger.info("seed_complete", extra={"file": str(path), **counts})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
