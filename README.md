# Stock Intelligence Platform

An AI-assisted research platform for Indian listed companies (NSE/BSE). Search a company, collect its prices, financials, news and filings, run AI summaries and sentiment analysis, and explore it all in Power BI dashboards.

> **Educational project, not investment advice.** Market data is delayed and comes from third-party sources, credited in the app. Sentiment scores describe news tone, not future price moves.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Database foundation + company search API | ✅ Done |
| 2 | Market data (prices, basic financials) with provider fallback | ✅ Done |
| 3 | News, exchange filings and company reports | ✅ Done |
| 4 | AI summaries and sentiment (Gemini) | ✅ Done |
| 5 | Scheduled and on-demand pipelines | ✅ Done |
| 6 | Power BI dashboards | Next |
| 7 | Next.js frontend | Planned |
| 8 | Testing and deployment | Planned |

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js + React (Vercel) |
| Backend | Python, FastAPI (Render) |
| Database | Supabase PostgreSQL |
| Data processing | Python, Pandas |
| Scheduling | APScheduler locally, GitHub Actions for the hosted demo |
| AI | Provider-independent adapter |
| Dashboards | Power BI (Import mode) |

## Architecture highlights

- **One company, many listings.** A company listed on both NSE and BSE is one row in `companies` with two rows in `company_listings`; ISIN sits on the listing because it identifies a security, not a company.
- **Provider adapters with fallback.** Every data source sits behind one interface. Prices are tried in order (Yahoo Finance → Upstox → EODHD); if one is down or has no data, the next is used, and each stored row records which provider supplied it.
- **News linked to companies, not just stored.** Headlines from publisher feeds, Google News and BSE filings are matched to companies by name, short name or BSE code, scored for relevance and stored once even when syndicated under several URLs.
- **Reports as searchable text.** Annual reports and results PDFs are downloaded once, checked by hash, and split into page-referenced chunks ready for AI analysis in Phase 4.
- **AI that can be checked.** Gemini rates each headline's tone for the company it's about and summarises annual reports. Answers must match a JSON schema; every summary point cites report pages, and any figure that isn't in the report text is dropped. Each result records its model and prompt version.
- **Sentiment history that doesn't drift.** Each finished day is scored once, weighted by how relevant each article is, and never rewritten; a new method gets a new version.
- **One pipeline, three triggers.** A refresh button (`POST /stocks/{ticker}/refresh`), the daily run and the hourly feeds run all go through the same steps and are recorded as jobs. Only one refresh per company can run at a time, a recent one is reused, and a crashed step never stops the others.
- **Idempotent by design.** Natural unique keys plus upserts mean a pipeline can be re-run safely.
- **Private by default.** Application tables live in an `app` schema that Supabase's public API does not expose, with row level security enabled on every table.
- **Provenance everywhere.** Every fact records its `data_sources` row, including licence and attribution details.

Full design notes: [`documentation/`](documentation/).

## Project structure

```
backend/            FastAPI application
  api/              HTTP routes
  core/             settings, logging, errors, middleware
  database/         connection, repositories (all SQL), seed loader
  providers/        data-source adapters (Yahoo, Upstox, EODHD) and the fallback chain
  schemas/          Pydantic request/response models
  services/         business logic
  tests/            pytest suite (runs against real Postgres)
database/
  migrations/       Alembic migrations, written as plain SQL
  seed/             seed data (5 test companies)
  views/            analytics views (Phase 6)
documentation/      architecture, database, API, decisions, checklist
```

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Service and database check |
| GET | `/stocks/search?q=` | Search by name, abbreviation, symbol, BSE code or ISIN (typo-tolerant) |
| GET | `/stocks/{ticker}?exchange=` | Company details with all listings |
| GET | `/stocks/{ticker}/prices?start=&end=&exchange=` | Daily OHLCV, each row tagged with its provider |
| GET | `/stocks/{ticker}/financials?period_type=` | Revenue, net profit, EPS, equity, shares outstanding |
| GET | `/stocks/{ticker}/news?min_relevance=&before=` | Recent headlines about the company, newest first, with relevance and source |
| GET | `/stocks/{ticker}/reports?document_type=` | Annual reports, results and filings, with text-extraction status |
| GET | `/stocks/{ticker}/sentiment?days=` | Daily AI-rated news sentiment and the period's overall tone |
| GET | `/stocks/{ticker}/analysis` | AI summaries of reports: key points and risks with page references |
| POST | `/stocks/{ticker}/refresh` | Start a refresh of one company; returns a job to poll |
| GET | `/jobs/{job_id}` | A job's status, step by step |
| GET | `/stocks/{ticker}/jobs` | The company's latest refreshes (when its data was last updated) |

Interactive docs at `/docs` when the server is running. Details: [`documentation/api.md`](documentation/api.md).

## Running locally

Requires Python 3.11+ and Docker (or any Postgres 15+).

```bash
docker compose up -d                          # local Postgres
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cp .env.example .env                          # defaults point at the Docker database

alembic upgrade head                          # create tables
python -m backend.database.seed               # load the 5 test companies
python -m backend.scheduler.run_once          # one full run: prices, news, filings, AI
uvicorn backend.main:app --reload             # http://localhost:8000/docs
python -m backend.scheduler.local             # optional: keep the daily and hourly schedules running

pytest                                        # full test suite
```

To use Supabase instead, put its **Session pooler** connection string (with `?sslmode=require`) in `DATABASE_URL`, then run the same migration and seed commands.

## Hosted setup

The database runs on Supabase (free plan). Data collection for the hosted demo runs on GitHub Actions:

1. In the repo: **Settings → Secrets and variables → Actions → New repository secret**, name `DATABASE_URL`, value = the Supabase **Session pooler** connection string with your password filled in.
2. Optional: add `EODHD_API_KEY` the same way to enable the third price source.
3. Optional: add `GEMINI_API_KEY` (free from Google AI Studio) to turn on AI sentiment and report summaries. Without it, everything else still runs.
4. **Actions → Collect market data, news and AI analysis → Run workflow.** It applies any new migrations, loads the seed companies, collects prices, financials, news and filings, then runs the AI analysis. After that it runs by itself every weekday at 19:30 IST.
5. **Collect news feeds and filings** runs hourly during market hours on weekdays. **Add a company document** adds a report by URL (for example an annual report PDF from the company's investor page) and extracts its text.

## Data sources

| Source | Used for | Notes |
|---|---|---|
| Manual seed | Company identifiers | From public exchange and company pages |
| Yahoo Finance (`yfinance`) | Prices (primary), financials, dividends and splits | Unofficial; personal and educational use |
| Upstox historical candles | Prices (fallback 1) | Public endpoint, no key; keyed by ISIN |
| EODHD free plan | Prices (fallback 2, optional) | Needs a free API key; 20 calls/day, last year only |
| Economic Times, Mint RSS | Market and company news | Headline, link and the feed's short description only |
| Google News search RSS | Company news | Headline, publisher and link; only headlines that name the company are kept |
| GDELT DOC API | Company news (best effort) | Often refuses cloud servers, so a failure is only a warning |
| BSE RSS feeds | Announcements, results and annual reports | Matched to companies by BSE scrip code |
| Company investor pages | Annual reports and presentations | Added by URL; text extracted from the PDF |
| Google Gemini API (free tier) | News sentiment, report summaries | Only public news and report text is sent; the model is set by `GEMINI_MODEL` |

Article bodies are never stored or republished; the app shows the headline and links to the publisher.

Company financials come from Yahoo only: no free fallback exists, so anything missing stays empty rather than estimated. A scheduled GitHub Actions job (`Live data check`) calls the real providers every weekday evening to catch breakages early.

## License

MIT
