# Database

Supabase PostgreSQL. Application tables live in the `app` schema; analytics views (Phase 6) in `analytics`.

## Conventions

- **Keys:** UUID for entities the API exposes; `bigint`/`smallint` identity or natural composite keys for high-volume rows.
- **Enumerations:** `text` + `CHECK` constraints (easier to change than Postgres enum types).
- **Time:** `timestamptz` for events; `date` for trading and period dates. `updated_at` is maintained by the `app.set_updated_at()` trigger.
- **Money:** `numeric`, never float; rupees in base units.
- **Deletes:** `RESTRICT` for facts, `CASCADE` only for pure child rows. Companies are deactivated, not deleted.
- **Security:** row level security enabled on every table with no policies; the Supabase `anon` and `authenticated` roles have no access to `app`. The backend connects with a privileged role.

## Phase 1 tables

| Table | Purpose | Key constraints |
|---|---|---|
| `data_sources` | Every provider, with terms, attribution and redistribution flag | unique `source_code` |
| `companies` | One row per issuer | unique `cin` (MCA Corporate Identification Number), format-checked |
| `company_listings` | One row per security per exchange | unique (exchange, symbol) while active; unique (exchange, exchange_code); unique (exchange, isin) while active; ISIN format check; symbol must be upper case |
| `company_aliases` | Names people search by | unique (company_id, normalised alias); trigram index for typo-tolerant search |
| `listing_provider_ids` | Each provider's own key for a listing | PK (listing_id, source_id); unique (source_id, provider_symbol) |

`alias_norm` is a generated column: lower case, non-alphanumerics collapsed to single spaces. The API applies the same rule to queries (`normalize_query`).

## How duplicates are prevented

- Companies are matched through their listings: ISIN first, then exchange + symbol. A BSE listing with the same ISIN as an NSE listing attaches to the same company.
- Listings never move between companies silently; the seed loader raises an error instead.
- Every write is an upsert on a natural key.

## Phase 2 tables

| Table | Purpose | Key constraints |
|---|---|---|
| `daily_prices` | One row per listing per trading day | PK (listing_id, trade_date); prices > 0; low ≤ open, close ≤ high; `price_basis` (raw, split_adjusted, unknown); `source_id` = the provider that actually supplied the row |
| `corporate_actions` | Dividends and splits (Yahoo reports bonuses as splits) | unique (listing_id, ex_date, action_type); dividends need an amount, splits a ratio |
| `metric_definitions` | Every metric: label, unit, whether derived | Five reported metrics; seven derived ones are defined but never stored |
| `financial_periods` | One reporting period per company | unique (company, period type, period end, consolidation, source, revision); Indian fiscal year and quarter |
| `financial_metrics` | Reported values | PK (period_id, metric_code); a trigger rejects derived metrics |

**Fiscal periods:** FY2027 runs April 2026 to March 2027; Q1 = Apr–Jun … Q4 = Jan–Mar.

**Known data difference:** before July 2023, Reliance's stored closes differ by a constant ~3.3% between Yahoo (NSE listing) and Upstox (BSE listing), because only one provider adjusted for the Jio Financial demerger. After that date they agree. Each listing's history comes from a single provider, so each series is internally consistent.

**Price adjustments:** Yahoo's prices are split-adjusted, so after a new split it rescales every earlier price. When the collector sees a new split or bonus, it re-fetches the listing's whole history so the stored series stays consistent.

## Planned tables

| Phase | Tables |
|---|---|
| 3 | `news_articles` (unique url_hash), `article_companies`, `company_documents`, `document_chunks` |
| 4 | `ai_analyses` (one per source × company × prompt version × model), `sentiment_history` (one per company × date × methodology version) |
| 5 | `collection_jobs` (doubles as the job queue) |
| 6 | `powerbi_refresh_queue` (optional), `analytics` views |

## Migrations

Alembic, in `database/migrations/`, written as plain SQL. The URL comes from `DATABASE_MIGRATION_URL` (falling back to `DATABASE_URL`), never from `alembic.ini`. The version table is `app.alembic_version`.

```bash
alembic upgrade head        # apply everything
alembic downgrade -1        # undo the last migration (local only)
alembic revision -m "..."   # new migration from the template
```

Rules: one concern per migration; never edit a migration that has been applied anywhere shared; every new table gets RLS enabled in the same migration.

| Migration | Contents |
|---|---|
| 0001 foundation | `extensions` and `app` schemas, `pg_trgm`, `set_updated_at()` |
| 0002 data_sources | provider registry |
| 0003 master_data | companies, listings, aliases, provider ids |
| 0004 security | RLS on all tables; revoke access from Supabase API roles |
| 0005 market | daily_prices, corporate_actions |
| 0006 financials | metric_definitions (with the 12 definitions), financial_periods, financial_metrics, derived-metric guard |
| 0007 function_search_path | pins `search_path` on the trigger functions (Supabase security advisor) |

## Hosted database (Supabase)

- Postgres 17, migrations at 0007, the five seed companies loaded.
- The `app` schema is not usable by the `anon` or `authenticated` roles, and RLS is on for every table.
- Supabase's security advisor reports one remaining **info** item, "RLS enabled, no policy", on each table. That is intentional: no policies means the API roles can read nothing, while the backend's privileged connection is unaffected.

## Seed data

`python -m backend.database.seed` loads `database/seed/companies.json` (5 test companies, 10 listings). It is idempotent and runs in one transaction. Identifiers are marked `"verified": false` until checked against NSE/BSE pages.
