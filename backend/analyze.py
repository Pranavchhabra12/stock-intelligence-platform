"""Command line: AI sentiment for recent news, report summaries, and daily sentiment history.

    python -m backend.analyze --all              # every company
    python -m backend.analyze INFY TCS           # chosen companies
    python -m backend.analyze --all --no-summaries

Without GEMINI_API_KEY the AI steps are skipped (exit 0) and only the daily
history is updated from analyses already stored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.database.connection import get_engine
from backend.database.repositories import CompanyRepository
from backend.providers.ai.gemini import GeminiClient
from backend.services.ai_analysis import AnalysisService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AI analysis")
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-sentiment", action="store_true")
    parser.add_argument("--no-summaries", action="store_true")
    parser.add_argument("--max-requests", type=int, default=None)
    args = parser.parse_args(argv)
    if not args.tickers and not args.all:
        parser.error("give one or more tickers, or --all")

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = get_engine()
    company_ids = None
    if args.tickers:
        with engine.connect() as conn:
            repo = CompanyRepository(conn)
            company_ids = []
            for ticker in args.tickers:
                cid = repo.find_company_id_by_ticker(ticker, None)
                if cid is None:
                    print(f"Unknown ticker: {ticker}", file=sys.stderr)
                    return 1
                company_ids.append(cid)

    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    ai = GeminiClient(key, settings.gemini_model) if key else None
    if ai is None:
        print("GEMINI_API_KEY is not set: skipping AI analysis, updating history only.", file=sys.stderr)

    service = AnalysisService(engine, ai, max_requests=args.max_requests or settings.ai_max_requests_per_run)
    result = service.run(company_ids, sentiment=not args.no_sentiment, summaries=not args.no_summaries)
    print(json.dumps({"analysis": {**vars(result), "status": result.status,
                                   "model": ai.model if ai else None}}))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for error in result.errors:
            print(f"::warning::{error}")
        if result.budget_exhausted:
            print("::notice::Request budget used up; the rest is analysed next run.")
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
