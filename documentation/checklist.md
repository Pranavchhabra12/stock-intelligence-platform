# Implementation checklist

## Phase 1: Foundation ✅

- [x] Monorepo scaffold, `.gitignore`, `.env.example`, README
- [x] Alembic configured; migrations 0001–0004 (schemas, data sources, master data, security)
- [x] Seed file for 5 test companies + idempotent loader
- [x] Settings, JSON logging with request IDs, consistent error format
- [x] Connection pool, repositories, company service
- [x] `GET /health`, `GET /stocks/search`, `GET /stocks/{ticker}`
- [x] Per-client rate limit, CORS
- [x] Tests: migration round trip, seed idempotency, constraints, search and lookup (34 tests)
- [x] GitHub Actions CI (lint + tests on Postgres 17)
- [ ] Create Supabase project (Mumbai region) and run migrations + seed against it
- [ ] Verify seed identifiers against NSE/BSE pages; set `"verified": true`

**Phase 1 acceptance criteria (blueprint):** tables created ✅ · company records insert and retrieve ✅ · NSE/BSE listings linked to one company ✅ · search returns the right company ✅ · no duplicate companies ✅

## Phase 2: Market data ✅

- [x] `MarketDataProvider` interface; Yahoo, Upstox and EODHD adapters with retries and request spacing
- [x] Fallback chain for prices; each row records its provider
- [x] Migrations 0005 (market) and 0006 (financials)
- [x] Historical backfill + incremental daily updates, upserted; full re-fetch after a new split
- [x] Corporate actions (splits, dividends)
- [x] Basic financials: revenue, net profit, EPS, shareholders' equity, shares outstanding
- [x] `GET /stocks/{ticker}/prices`, `GET /stocks/{ticker}/financials`
- [x] CLI: `python -m backend.collect RELIANCE` / `--all`
- [x] Offline tests for adapters, fallback, collector and API; live-data workflow
- [ ] Run against Supabase once the project exists

**Phase 2 acceptance criteria (blueprint):** retrieve market data for a searched company ✅ · historical prices stored ✅ · duplicate price records prevented ✅ · source and timestamps retained ✅ · missing information handled safely ✅

## Phase 3: News and reports

- [ ] News adapters: GDELT, publisher RSS
- [ ] Exchange announcements (BSE RSS)
- [ ] Company documents and PDF text extraction

## Later phases

See the project plan: news and reports (3), AI analysis (4), automation (5), Power BI (6), frontend (7), testing and deployment (8).
