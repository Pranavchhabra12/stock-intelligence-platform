"""Load every NSE-listed company from NSE's official equity list, so search can find them all.

    python -m backend.database.load_universe                 # download from NSE
    python -m backend.database.load_universe --file EQUITY_L.csv

New companies are added untracked: searchable and viewable, but not collected daily or
analysed until someone adds them to Power BI. Companies already in the database (matched by
ISIN or NSE symbol) are left as they are. The whole load is a handful of set-based
statements, so it takes seconds even over a slow connection.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys

import httpx
from sqlalchemy import Engine, text

from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.database.connection import get_engine

NSE_EQUITY_LIST = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
_ISIN = re.compile(r"^IN[A-Z0-9]{9}[0-9]$")
_SUFFIX = re.compile(r"\s+(limited|ltd\.?)$", re.I)
_SYMBOL = re.compile(r"^[A-Z0-9&.\-]{1,20}$")


def short_name(legal: str) -> str:
    """'Tata Motors Limited' -> 'Tata Motors' (the legal name is kept separately)."""
    return _SUFFIX.sub("", legal.strip()) or legal.strip()


def parse(csv_text: str) -> list[dict]:
    """Rows from NSE's EQUITY_L.csv. Its headers carry stray spaces, so they are normalised."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows, seen = [], set()
    for raw in reader:
        r = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items()}
        symbol, legal = r.get("SYMBOL", "").upper(), r.get("NAME OF COMPANY", "")
        isin = r.get("ISIN NUMBER", "").upper()
        if not _SYMBOL.match(symbol) or not legal or not _ISIN.match(isin) or symbol in seen:
            continue
        seen.add(symbol)
        rows.append({"symbol": symbol, "legal": legal, "name": short_name(legal), "isin": isin,
                     "series": r.get("SERIES") or None})
    return rows


def download(client: httpx.Client | None = None) -> str:
    client = client or httpx.Client(timeout=60, follow_redirects=True, headers={
        # NSE's archive refuses requests without a browser-like user agent.
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
        "Accept": "text/csv,*/*",
    })
    response = client.get(NSE_EQUITY_LIST)
    response.raise_for_status()
    return response.text


def load(engine: Engine, rows: list[dict]) -> dict[str, int]:
    if len(rows) < 100:
        raise ValueError(f"only {len(rows)} usable rows; refusing to load a partial list")
    with engine.begin() as conn:
        conn.execute(text(
            """
            create temporary table nse_list (
              symbol text, legal text, name text, isin text, series text,
              company_id uuid default gen_random_uuid(), is_new boolean default false
            ) on commit drop
            """
        ))
        conn.execute(text("insert into nse_list (symbol, legal, name, isin, series) "
                          "values (:symbol, :legal, :name, :isin, :series)"), rows)
        conn.execute(text(
            """
            update nse_list u set is_new = true
            where not exists (select 1 from app.company_listings l
                              where l.isin = u.isin or (l.exchange = 'NSE' and l.symbol = u.symbol))
            """
        ))
        added = conn.execute(text(
            """
            insert into app.companies (company_id, company_name, legal_name)
            select company_id, name, legal from nse_list where is_new
            """
        )).rowcount
        conn.execute(text(
            """
            insert into app.company_listings (company_id, exchange, symbol, isin, series)
            select company_id, 'NSE', symbol, isin, series from nse_list where is_new
            """
        ))
        conn.execute(text(
            """
            insert into app.company_aliases (company_id, alias, alias_type)
            select company_id, name, 'name' from nse_list where is_new
            union all
            select company_id, legal, 'legal_name' from nse_list where is_new and legal <> name
            union all
            select company_id, symbol, 'symbol' from nse_list where is_new
            on conflict do nothing
            """
        ))
        total = conn.execute(text("select count(*) from app.companies where is_active")).scalar_one()
        tracked = conn.execute(text("select count(*) from app.companies where is_tracked")).scalar_one()
    return {"rows_in_list": len(rows), "companies_added": added, "companies_total": total, "tracked": tracked}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load NSE's list of listed companies")
    parser.add_argument("--file", help="a local copy of EQUITY_L.csv instead of downloading it")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    csv_text = open(args.file, encoding="utf-8-sig").read() if args.file else download()
    try:
        result = load(get_engine(), parse(csv_text))
    except ValueError as exc:
        print(f"Not loaded: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
