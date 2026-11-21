# Architecture

## Layers

```
Next.js frontend ──REST──▶ FastAPI backend ──▶ Supabase PostgreSQL ◀── Power BI Desktop
                               │                     ▲
                               ▼                     │
                       Provider adapters ────────────┘
             (market data, news, filings, AI models)
```

- **Frontend** (Phase 7): search, company pages, job progress, AI summaries.
- **Backend**: FastAPI. Routes in `api/` stay thin; rules live in `services/`; all SQL lives in `database/repositories.py`.
- **Adapters** (Phase 2+): one interface per kind of provider, so a source can be replaced by writing one class.
- **Database**: Supabase Postgres is the single source of truth. Tables live in the private `app` schema; Power BI reads only `analytics` views (Phase 6).
- **Power BI**: Desktop, Import mode, reading the `analytics` views. Shared as screenshots and a recording.

## Pipelines (Phase 5)

One pipeline, two triggers:

- **On demand:** `POST /stocks/{ticker}/refresh` saves a `pending` row in `collection_jobs` and returns a `job_id`; a background task does the work; the frontend polls `GET /jobs/{job_id}`. A partial unique index allows only one active job per company and job type.
- **Scheduled:** `python -m backend.scheduler.run_once`. APScheduler calls it locally; in the hosted demo a GitHub Actions workflow runs it once a day after market close. (Free Render instances sleep after 15 minutes idle, so an in-process scheduler cannot run there.)

## Hosting (free tiers)

| Part | Host |
|---|---|
| Frontend | Vercel |
| Backend API | Render (free web service) |
| Daily pipeline | GitHub Actions scheduled workflow |
| Database and file storage | Supabase Free |

## Key rules

- Never fabricate data: missing values are `NULL`, with their source recorded.
- AI output never becomes an authoritative financial figure.
- Retrieved text is untrusted input to the AI, never instructions.
- Historical prices and sentiment are never overwritten; methodology changes create new versions.
- Secrets only in environment variables; the service-role key never reaches the frontend.

See [decisions.md](decisions.md) for the reasoning behind each choice.
