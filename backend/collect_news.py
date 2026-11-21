"""Command line: collect news and exchange filings, then process new documents.

    python -m backend.collect_news --all              # every company, all sources
    python -m backend.collect_news RELIANCE TCS       # chosen companies
    python -m backend.collect_news --all --no-gdelt   # feeds only

Exit code 1 only if every source failed or a document could not be processed.
A single source being down (GDELT is often busy) is reported as a warning.
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
from backend.providers.news.gdelt import GdeltNewsAdapter
from backend.providers.news.rss import RssAdapter
from backend.services.document_service import DocumentService
from backend.services.news_collector import NewsCollector


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect news, filings and documents")
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-gdelt", action="store_true", help="skip the GDELT search")
    parser.add_argument("--no-feeds", action="store_true", help="skip RSS feeds")
    parser.add_argument("--no-documents", action="store_true", help="don't download new documents")
    args = parser.parse_args(argv)
    if not args.tickers and not args.all:
        parser.error("give one or more tickers, or --all")

    configure_logging(get_settings().log_level)
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

    collector = NewsCollector(engine, gdelt=None if args.no_gdelt else GdeltNewsAdapter(),
                              rss=None if args.no_feeds else RssAdapter())
    news = collector.collect(company_ids)
    print(json.dumps({"news": {**vars(news), "status": news.status}}))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for error in news.errors:
            print(f"::warning::{error}")
    ok = news.status != "failed"

    if not args.no_documents:
        docs = DocumentService(engine).ingest_pending()
        print(json.dumps({"documents": vars(docs)}))
        ok &= docs.failed == 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
