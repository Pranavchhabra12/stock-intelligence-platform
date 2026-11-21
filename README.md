# Stock Intelligence Platform

An AI-assisted research platform for Indian listed companies (NSE/BSE). Search a company, collect its prices, financials, news and filings, run AI summaries and sentiment analysis, and explore it all in Power BI dashboards.

> **Educational project, not investment advice.** Market data is delayed and comes from third-party sources, credited in the app. Sentiment scores describe news tone, not future price moves.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Database foundation + company search API | ✅ Done |
| 2 | Market data (prices, basic financials) | Next |
| 3 | News and company reports | Planned |
| 4 | AI summaries and sentiment | Planned |
| 5 | Scheduled and on-demand pipelines | Planned |
| 6 | Power BI dashboards | Planned |
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
- **Provider adapters.** Every data source sits behind an interface, and each provider's own instrument key is stored in `listing_provider_ids`, so a provider can be swapped without touching the rest of the app.
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
  schemas/          Pydantic request/response models
  services/         business logic
  tests/            pytest suite (runs against real Postgres)
database/
  migrations/       Alembic migrations, written as plain SQL
  seed/             seed data (5 test companies)
  views/            analytics views (Phase 6)
documentation/      architecture, database, API, decisions, checklist
```

## API (Phase 1)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Service and database check |
| GET | `/stocks/search?q=` | Search by name, abbreviation, symbol, BSE code or ISIN (typo-tolerant) |
| GET | `/stocks/{ticker}?exchange=` | Company details with all listings |

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
uvicorn backend.main:app --reload             # http://localhost:8000/docs

pytest                                        # full test suite
```

To use Supabase instead, put its **Session pooler** connection string (with `?sslmode=require`) in `DATABASE_URL`, then run the same migration and seed commands.

## Data sources

| Source | Used for | Notes |
|---|---|---|
| Manual seed | Company identifiers | From public exchange and company pages |
| Yahoo Finance (`yfinance`) | Prices and basic financials (Phase 2) | Unofficial; personal and educational use |

## License

MIT
