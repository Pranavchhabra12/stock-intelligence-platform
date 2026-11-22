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
- [x] Create Supabase project and run migrations + seed against it
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
- [x] Database ready on Supabase (migrations 0001–0007, seed loaded, security advisor clean)
- [x] Add the `DATABASE_URL` repository secret and run the **Collect market data** workflow

**Phase 2 acceptance criteria (blueprint):** retrieve market data for a searched company ✅ · historical prices stored ✅ · duplicate price records prevented ✅ · source and timestamps retained ✅ · missing information handled safely ✅

## Phase 3: News and reports ✅

- [x] Migration 0008: `news_articles`, `article_companies`, `company_documents`, `document_chunks`, per-company exclusion phrases
- [x] News adapters: Economic Times and Mint RSS, Google News search, GDELT (best effort)
- [x] Exchange announcements, results and annual reports from BSE RSS, matched by scrip code
- [x] Company matcher with relevance scores and look-alike exclusions
- [x] Deduplication by canonical URL and by headline within two days
- [x] Company documents: add by URL, PDF download, hash check, text by page, chunking, scanned-PDF detection
- [x] `GET /stocks/{ticker}/news` and `GET /stocks/{ticker}/reports`
- [x] Workflows: daily news step, hourly feeds, manual "Add a company document"
- [x] Verified on Supabase: about 190 articles linked across the five companies

**Phase 3 acceptance criteria (blueprint):** news collected for a searched company ✅ · articles linked to the right company ✅ · duplicates prevented ✅ · sources and timestamps retained ✅ · reports stored with extracted text ✅

## Phase 4: AI analysis ✅

- [x] Migration 0009: `ai_analyses`, `sentiment_history`
- [x] Gemini client: REST, JSON schema output, request spacing, retries, bad-key detection
- [x] Article sentiment in batches, validated, never repeated for the same model and prompt
- [x] Report summaries with page references; unverifiable figures and pages dropped
- [x] Daily sentiment history: relevance-weighted, finished days only, written once
- [x] `GET /stocks/{ticker}/sentiment`, `GET /stocks/{ticker}/analysis`, sentiment on `/news`
- [x] AI step in the daily workflow; live Gemini check

**Phase 4 acceptance criteria (blueprint):** AI summaries generated from stored content ✅ · sentiment per article and per company ✅ · model and prompt version recorded ✅ · AI never produces financial figures ✅ · history kept, not overwritten ✅

## Phase 5: Pipelines ✅

- [x] Migration 0010: `collection_jobs` with one active job per company and type
- [x] Shared pipeline: prices → news → documents → AI, each step isolated and saved as it finishes
- [x] `POST /stocks/{ticker}/refresh` (background task, cooldown, busy limit), `GET /jobs/{job_id}`, `GET /stocks/{ticker}/jobs`
- [x] Stuck jobs expire after 45 minutes
- [x] `backend.scheduler.run_once` (daily, hourly feeds, chosen companies) and `backend.scheduler.local` (APScheduler)
- [x] Both GitHub Actions schedules now call the same pipeline

**Phase 5 acceptance criteria (blueprint):** refresh on demand without blocking ✅ · job status visible ✅ · duplicate jobs prevented ✅ · scheduled runs automated ✅ · failures recorded, not hidden ✅

## Phase 7: Website ✅

- [x] Next.js app in `frontend/`: home, company page, "How it works", not-found and error pages
- [x] Search with keyboard support; every tracked company with its latest close and a 30-day news-tone strip
- [x] Company page: price and 52-week range, tone strip, price chart (1M to 5Y), key numbers with their basis, results table, annual-report summary with pages, news with tone filters, reports list, refresh with live step progress
- [x] `GET /stocks` and `GET /stocks/{ticker}/summary` in the API
- [x] Responsive down to phone width; keyboard focus, screen-reader text for charts, reduced motion respected; colour-blind-safe tone colours
- [x] Polish pass: featured company in the home hero, translucent sticky header, a slim bar with the company and price on long pages, jump links on phones, 44px tap targets, pressed and hover states, skip link
- [x] Share images for the home page and every company page (link previews on LinkedIn)
- [x] After a refresh, that company's cached data is cleared and changed figures glow once
- [x] CI type-checks and builds the website

**Phase 7 acceptance criteria (blueprint):** search and view a company ✅ · prices, financials, news, sentiment and AI summaries shown ✅ · sources and disclaimers visible ✅ · refresh from the page ✅ · works on mobile ✅

## After launch

- [x] All NSE companies searchable (monthly load from NSE's equity list)
- [x] "Add to Power BI" with a cap of 25; untracked companies fetched on first visit
- [x] Company page in one request; no prefetching from the home page; website functions in Singapore
- [x] One search box on the home page

## Later phases

See the project plan: automation (5), Power BI (6), frontend (7), testing and deployment (8).
