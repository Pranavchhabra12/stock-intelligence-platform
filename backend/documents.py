"""Command line: add a company document by URL and process it.

    python -m backend.documents add RELIANCE annual_report "https://.../annual-report.pdf" \\
        --title "Annual Report 2025-26" --date 2026-07-01 --period FY2026
    python -m backend.documents process          # download and extract pending documents
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.database.connection import get_engine
from backend.database.repositories import CompanyRepository
from backend.services.document_service import DOCUMENT_TYPES, DocumentService, IngestResult


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Company documents")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="register a document by URL and process it")
    add.add_argument("ticker")
    add.add_argument("document_type", choices=DOCUMENT_TYPES)
    add.add_argument("url")
    add.add_argument("--title", required=True)
    add.add_argument("--date", type=date.fromisoformat, help="publication date, YYYY-MM-DD")
    add.add_argument("--period", help="fiscal period, e.g. FY2026 or Q2 FY2027")
    process = sub.add_parser("process", help="download and extract pending documents")
    process.add_argument("--retry-failed", action="store_true")
    process.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    configure_logging(get_settings().log_level)
    engine = get_engine()
    service = DocumentService(engine)

    if args.command == "add":
        with engine.connect() as conn:
            company_id = CompanyRepository(conn).find_company_id_by_ticker(args.ticker, None)
        if company_id is None:
            print(f"Unknown ticker: {args.ticker}", file=sys.stderr)
            return 1
        try:
            document_id = service.add(company_id, args.url, args.document_type, args.title, args.date, args.period)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        result = IngestResult()
        service.ingest(document_id, args.url, None, result)
    else:
        result = service.ingest_pending(limit=args.limit, include_failed=args.retry_failed)

    print(json.dumps(vars(result)))
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
