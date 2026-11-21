"""Command line: collect market data for one or more companies.

    python -m backend.collect RELIANCE TCS     # by NSE symbol (or BSE code)
    python -m backend.collect --all            # every active company

Exit code 0 if everything succeeded, 1 if any company had errors.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.database.connection import get_engine
from backend.database.repositories import CompanyRepository
from backend.providers.market_data import build_market_data_provider
from backend.services.market_data import MarketDataCollector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect market data")
    parser.add_argument("tickers", nargs="*", help="NSE symbols or BSE codes")
    parser.add_argument("--all", action="store_true", help="collect every active company")
    args = parser.parse_args(argv)
    if not args.tickers and not args.all:
        parser.error("give one or more tickers, or --all")

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = get_engine()

    with engine.connect() as conn:
        if args.all:
            company_ids = list(conn.execute(text("select company_id from app.companies where is_active")).scalars())
        else:
            repo = CompanyRepository(conn)
            company_ids = []
            for ticker in args.tickers:
                cid = repo.find_company_id_by_ticker(ticker, None)
                if cid is None:
                    print(f"Unknown ticker: {ticker}", file=sys.stderr)
                    return 1
                company_ids.append(cid)

    eodhd_key = settings.eodhd_api_key.get_secret_value() if settings.eodhd_api_key else None
    provider = build_market_data_provider(settings.market_data_provider_codes, eodhd_key)
    collector = MarketDataCollector(engine, provider, backfill_years=settings.price_backfill_years)
    ok = True
    for cid in company_ids:
        result = collector.collect_company(cid)
        ok &= result.status == "completed"
        print(json.dumps({k: str(v) if k == "company_id" else v for k, v in vars(result).items()}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
