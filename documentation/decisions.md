# Decision log

Short records of architectural choices and why they were made. The finalised stack (Next.js, FastAPI, Supabase, APScheduler, Power BI Import) is unchanged by any of these.

| # | Decision | Why |
|---|---|---|
| 1 | Scope: portfolio project on free tiers | Built to demonstrate engineering, not to run as a business |
| 2 | ISIN on `company_listings`, not `companies` | ISIN identifies a security; one company can have several |
| 3 | Search aliases table with trigram index | Lets "RIL", "Tata Consultancy" and typos like "relaince" find the right company |
| 4 | `listing_provider_ids` table | Each provider names instruments differently; keeps adapters swappable |
| 5 | Tables in a private `app` schema, RLS on everything | Supabase's public API cannot read them even if misconfigured |
| 6 | SQLAlchemy Core + psycopg 3, not supabase-py | Transactions and `ON CONFLICT` upserts; explicit SQL |
| 7 | Alembic with hand-written SQL, no autogenerate | The SQL reviewed is the SQL that runs |
| 8 | `text` + `CHECK` instead of Postgres enums | Easier to change in migrations |
| 9 | Session pooler connection, prepared statements off | Render cannot reach Supabase's IPv6 direct connection; works behind any pooler mode |
| 10 | Primary price source: `yfinance` (Phase 2) | Free, no account; wrapped in an adapter with retries and caching because it is unofficial |
| 11 | Scheduled runs: APScheduler locally, GitHub Actions in the hosted demo | Free Render instances sleep, so an in-process scheduler cannot run there |
| 12 | `collection_jobs` doubles as the job queue | Retries and dedupe without adding Redis/Celery |
| 13 | Basic, bank-friendly metric set | Price, market cap, P/E, P/B, dividend yield, revenue, net profit, EPS, ROE, growth: all apply to banks, so nothing is "not applicable" |
| 14 | Power BI Desktop, shared via screenshots | Power BI Service cannot refresh from Supabase without a gateway; "Publish to web" would make data public |
| 15 | Store raw prices; adjust in a view | Adjusted closes change after splits, which would rewrite history |
| 16 | AI analyses keyed by source × company | One article can be good news for one company and bad for another |
| 17 | Price fallback chain: Yahoo → Upstox → EODHD | Yahoo is unofficial and can fail; Upstox's historical endpoint is public and keyed by ISIN; EODHD's free plan covers the last year. Each row records its provider |
| 18 | Adapters derive their own symbols from a `ListingKey` | Provider-specific identifiers stay inside adapters; `listing_provider_ids` only holds exceptions |
| 19 | Upstox marked `split_adjusted`; EODHD stays `unknown` | Five years of Upstox BSE closes match Yahoo NSE closes to ~0.04% across bonus issues. EODHD hasn't been compared yet |
| 20 | Derived metrics blocked by a database trigger | Market cap, P/E and the like are always computed from stored values, never stored |
| 21 | Live provider tests run in a separate, non-blocking workflow | External outages shouldn't fail normal CI, but breakages still get noticed daily |
| 22 | A thin answer counts as missing data | Yahoo returned one day of BSE history for four companies; the fallback now needs ≥80% of weekdays, and the collector fills gaps at the front of a listing's history |
| 23 | Store headlines and links, never article bodies | Respects publishers' terms; the headline is enough to link and score an article, and readers click through |
| 24 | Search results must name the company in the headline | Search engines match the whole article; body-only mentions were mostly market round-ups and noise |
| 25 | Google News search per company; GDELT best effort | GDELT refused GitHub's runner IPs even for a single request; Google News search RSS works from servers and is free |
| 26 | BSE filings matched by scrip code | The code in each BSE item identifies the company exactly, so no name matching is needed |
| 27 | Reports chunked by page, about 1,500 words each | Keeps chunks within AI context limits and lets answers cite page numbers |
| 28 | Scanned PDFs marked `needs_ocr`, not OCR'd | OCR is slow and error-prone on free hosting; most listed companies publish text PDFs |
| 29 | Gemini (free tier) through its REST API, no SDK | Free and capable enough for short ratings and summaries; plain HTTP is explicit and easy to test. The model name is a setting |
| 30 | Headlines rated in batches of 20 | Keeps a day's news to a handful of requests, well inside free-tier limits |
| 31 | Summary points must cite real pages and real figures | The model only sees selected pages; anything citing other pages, or a number not in that text, is dropped rather than trusted |
| 32 | Sentiment history only for finished, fully rated days | A run that runs out of budget can't leave a partial day that is then frozen |
| 33 | Free-tier data terms accepted for this project | Only public news and published reports are sent, never user data |
