# Deployment

Everything runs on free plans.

| Part | Host | Notes |
|---|---|---|
| Website | Vercel (Hobby) | Next.js, root directory `frontend`, deploys on every push to `main` |
| API | Render (free web service), Singapore | FastAPI; sleeps after 15 minutes idle, so the first request after a quiet spell takes about a minute |
| Database | Supabase (free), Sydney | Reached through the session pooler (IPv4) |
| Daily and hourly data runs | GitHub Actions | `run_once` pipeline; doesn't depend on the API being awake |

```
browser ──► Vercel (Next.js) ──/api/* proxy──► Render (FastAPI) ──► Supabase Postgres
                 │ page renders (with X-Internal-Key) ──┘                 ▲
GitHub Actions (daily 19:30 IST, hourly feeds) ──────────────────────────┘
```

## Settings

**Render** (`render.yaml` holds the same configuration as a Blueprint):

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase **Session pooler** connection string with the password (secret) |
| `GEMINI_API_KEY` | From Google AI Studio (secret) |
| `INTERNAL_API_KEY` | A long random string, the same as on Vercel (secret) |
| `APP_ENV`, `LOG_LEVEL`, `API_RATE_LIMIT_PER_MINUTE`, `DB_POOL_SIZE`, `PYTHON_VERSION` | `prod`, `INFO`, `60`, `3`, `3.12.8` |

**Vercel** (project root directory `frontend`):

| Variable | Value |
|---|---|
| `API_URL` | The Render service URL |
| `INTERNAL_API_KEY` | The same random string as on Render (sensitive) |

**GitHub Actions secrets:** `DATABASE_URL`, `GEMINI_API_KEY`, and optionally `EODHD_API_KEY`.

## Why the shared key

Pages are rendered on Vercel's servers, so every page render reaches the API from the same few
IPs and would share one visitor's rate limit. Those requests send `X-Internal-Key`; the API
compares it in constant time and skips the limit only when it matches. Browser requests through
`/api/*` carry the visitor's own IP and stay limited.

## Updating

Merging to `main` redeploys both the website and the API. Database migrations run in the daily
GitHub Actions job (`alembic upgrade head`), before any collection.
