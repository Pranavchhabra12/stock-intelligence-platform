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
- **Adapters**: one interface per kind of provider, so a source can be replaced by writing one class. Prices go through a fallback chain (Yahoo Finance → Upstox → EODHD); each stored row records which provider supplied it.
- **Database**: Supabase Postgres is the single source of truth. Tables live in the private `app` schema; Power BI reads only `analytics` views (Phase 6).
- **Power BI**: Desktop, Import mode, reading the `analytics` views. Shared as screenshots and a recording.

## News and reports (Phase 3)

```
publisher RSS ─┐
Google News ───┼─► company matcher ─► news_articles + article_companies (deduplicated)
GDELT ─────────┘
BSE filing RSS ─► match by BSE code ─► news_articles + company_documents
company_documents ─► download PDF ─► SHA-256 check ─► text by page ─► document_chunks
```

- The matcher removes look-alike names first ("Reliance Power", "HDFC Life", "Infosys Prize"), then looks for full names (case-insensitive) and short codes such as "RIL" or "TCS" (case-sensitive).
- Search results only count if the headline names the company; quote pages and social posts are skipped.
- A document is re-extracted only when its file hash changes. Scanned PDFs with no text layer are marked `needs_ocr` rather than guessed at.

## AI analysis (Phase 4)

```
recent articles (relevance ≥ 0.6) ─► batches of 20 ─► Gemini (JSON schema) ─► checks ─► ai_analyses
extracted reports ─► best ~24,000 words ─► Gemini ─► page + figure checks ─► ai_analyses
ai_analyses ─► finished, fully rated days ─► sentiment_history (written once)
```

- Headlines and report text are sent as marked-off data, and the prompt tells the model to ignore instructions inside them.
- A sentiment answer is rejected if its label and score disagree or are out of range.
- Report text is sent as numbered parts; the model cites parts, which are stored as the PDF pages they cover (printed page numbers in reports often differ). A point is dropped if it cites a part the model wasn't given, or uses a figure that isn't in the text.
- Each run has a request budget (`AI_MAX_REQUESTS_PER_RUN`); whatever is left is picked up next run. A bad key stops the run after one request.

## Website (Phase 7)

Next.js (App Router) in `frontend/`, deployed separately from the API.

- Pages: home (search and every tracked company with a 30-day tone strip), a page per company (`/stocks/{ticker}`) and "How it works".
- Server components fetch from the API with a five-minute cache, so most visits never wait on the backend. Every section loads independently: if one call fails, that section says so and the rest of the page still shows.
- The browser only calls `/api/*` on the site itself; Next forwards those requests to the API (`API_URL`). No cross-origin requests, and the API address lives in one setting.
- Interactive parts (search, chart ranges, the results toggle, news filters, the refresh button) are small client components. The refresh button starts a job and polls it, showing each step, then reloads the page data.
- Key numbers come from `GET /stocks/{ticker}/summary`, worked out on request from stored prices and results (see decision 37).
- News tone uses blue for positive and orange for negative, which stay distinct for colour-blind readers; price moves always carry a sign and an arrow as well as colour.

## Pipelines (Phase 5)

One pipeline (`backend/services/pipeline.py`), three triggers, every run recorded in `collection_jobs`:

| Trigger | Job type | Steps | Runs |
|---|---|---|---|
| `POST /stocks/{ticker}/refresh` | `company_refresh` | prices → news → documents → AI | in the API, as a background task |
| Daily schedule | `scheduled_run` | the same, for every company, plus GDELT | weekdays 19:30 IST |
| Hourly schedule | `feeds_run` | news → documents → AI | weekdays 09:00–19:00 IST |

- The refresh endpoint saves a `pending` job and returns it at once; the client polls `GET /jobs/{job_id}`, which shows each step as it finishes.
- A partial unique index allows one pending or running job per company and job type, so double clicks and overlapping schedules can't start a second one.
- A refresh that finished within the cooldown (15 minutes) is returned instead of starting another; failed ones can be retried at once. At most three jobs run at a time.
- Each step is isolated: a crash is recorded on that step and the next one still runs.
- A job stuck in `running` (say, the server restarted) is marked failed after 45 minutes, so it can't block its company.
- Schedules: `python -m backend.scheduler.run_once` is the single entry point. In the hosted demo GitHub Actions calls it; locally `python -m backend.scheduler.local` runs both schedules with APScheduler. (Free Render instances sleep after 15 minutes idle, so an in-process scheduler can't run there.)

## Hosting (free tiers)

| Part | Host |
|---|---|
| Website | Vercel (Next.js, root directory `frontend`) |
| Backend API | Render (free web service) |
| Daily pipeline | GitHub Actions scheduled workflow (prices, financials, news, AI analysis) |
| AI model | Google Gemini API, free tier |
| Hourly feeds | GitHub Actions, weekdays during market hours |
| Database and file storage | Supabase Free |

## Key rules

- Never fabricate data: missing values are `NULL`, with their source recorded.
- AI output never becomes an authoritative financial figure.
- Retrieved text is untrusted input to the AI, never instructions.
- Historical prices and sentiment are never overwritten; methodology changes create new versions.
- Secrets only in environment variables; the service-role key never reaches the frontend.

See [decisions.md](decisions.md) for the reasoning behind each choice.
