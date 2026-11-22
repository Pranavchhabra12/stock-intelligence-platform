# API

Base URL locally: `http://localhost:8000`. Interactive docs: `/docs`.

Every response carries an `X-Request-ID` header (echoed from the request if supplied), which also appears in the logs.

## Error format

All errors share one shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "No company found for ticker 'NOSUCHCO'.",
    "details": null,
    "request_id": "f34f25b13b6643eb81a1c95571711a66"
  }
}
```

| Status | `code` |
|---|---|
| 404 | `not_found` |
| 422 | `validation_error` (`details` lists each field and problem) |
| 429 | `rate_limited` (with a `Retry-After` header) |
| 500 | `internal_error` (details go to the logs only) |
| 503 | `service_unavailable` |

## Endpoints

### `GET /health`

```json
{"status": "ok", "database": "ok"}
```

Returns 503 if the database is unreachable. Not rate limited.

### `GET /stocks/search`

| Parameter | Type | Notes |
|---|---|---|
| `q` | string, 2–64 chars | Name, abbreviation, NSE/BSE symbol, BSE scrip code or ISIN. Needs at least 2 letters or digits |
| `limit` | int, 1–25 | Default 10 |

Ranking: exact identifier (score 1.0) > exact alias (0.95) > alias prefix (0.90) > trigram similarity (typos). Each company appears once, with all its listings. No match returns `200` with an empty list.

```
GET /stocks/search?q=relaince
```
```json
{
  "query": "relaince",
  "count": 1,
  "results": [
    {
      "company_id": "36a07395-…",
      "company_name": "Reliance Industries",
      "sector": null,
      "industry": null,
      "score": 0.327,
      "listings": [
        {"listing_id": "…", "exchange": "NSE", "symbol": "RELIANCE", "exchange_code": null,
         "isin": "INE002A01018", "series": "EQ", "currency": "INR", "is_active": true},
        {"listing_id": "…", "exchange": "BSE", "symbol": "RELIANCE", "exchange_code": "500325",
         "isin": "INE002A01018", "series": null, "currency": "INR", "is_active": true}
      ]
    }
  ]
}
```

### `GET /stocks/{ticker}`

| Parameter | Notes |
|---|---|
| `ticker` (path) | 1–20 chars: letters, digits, `&`, `.`, `-` |
| `exchange` (query) | Optional `NSE` or `BSE` |

Without `exchange`: tries the NSE symbol, then the BSE scrip id or code, then ISIN. With `exchange=BSE`: matches the BSE scrip id or code.

Returns company details, all listings and aliases. `GET /stocks/RELIANCE` and `GET /stocks/500325?exchange=BSE` return the same `company_id`.

### `GET /stocks/{ticker}/prices`

| Parameter | Notes |
|---|---|
| `exchange` | Optional; NSE by default, `BSE` for the BSE listing |
| `start`, `end` | Dates; default the last 365 days; at most 10 years; `start` ≤ `end` |

Returns daily OHLCV oldest first. Each row has a `source` (the provider that supplied it); `sources` lists their names and attribution text; `price_basis` is `split_adjusted`, `raw`, `unknown`, or `mixed` when rows came from providers with different bases.

### `GET /stocks/{ticker}/financials`

| Parameter | Notes |
|---|---|
| `period_type` | `quarterly` (default) or `annual` |
| `limit` | 1–40, default 8 |

Periods newest first, labelled like `Q2 FY2027` or `FY2026`. Every reported metric appears in each period; ones the source did not report are `null`.

### `GET /stocks/{ticker}/news`

| Parameter | Notes |
|---|---|
| `limit` | 1–100, default 20 |
| `min_relevance` | 0–1, default 0.5. Relevance is 1.0 when the headline names the company, 0.85 for a short name such as "Infosys" or "RIL", and 0.6 when only the feed's description mentions it |
| `before` | Page cursor: pass `next_before` from the previous page |

Articles come newest first. Each has its headline, link, publisher, published time, relevance, `source` (the feed or search that found it) and that source's attribution text. Article bodies are not stored.

### `GET /stocks/{ticker}/reports`

| Parameter | Notes |
|---|---|
| `document_type` | Optional: `annual_report`, `quarterly_results`, `investor_presentation`, `exchange_filing`, `earnings_transcript`, `other_disclosure` |

Documents newest first, with `extraction_status` (`pending`, `extracted`, `needs_ocr` for scanned PDFs, `not_pdf`, `failed`), page count and how many text chunks are ready for analysis.

### `GET /stocks/{ticker}/sentiment`

| Parameter | Notes |
|---|---|
| `days` | 7–90, default 30 |

`history` lists each finished day (India time) that had rated news, oldest first: the relevance-weighted score from −1 to 1 and how many articles were positive, neutral and negative. `overall_score` is the article-weighted mean over the period; `overall_label` is positive above 0.15, negative below −0.15, otherwise neutral. `methodology_version` says how the numbers were made.

News items from `/news` also carry `sentiment` and `sentiment_score` once they've been rated.

### `GET /stocks/{ticker}/analysis`

AI summaries of the company's reports, newest report first: `summary`, `key_points` and `risks`, where every point lists the report pages it comes from. Each summary records the `model` and `prompt_version` that produced it.

### `POST /stocks/{ticker}/refresh`

Starts a refresh of one company: latest prices, news, filings and documents, then AI analysis. Returns at once.

- **202**: a new refresh was started (`created: true`), or one is already pending or running (`created: false`).
- **200**: a refresh finished within the cooldown (15 minutes by default); it is returned instead of starting another.
- **429** with code `busy`: too many refreshes are running; try again in a few minutes.

The response includes `job_id` and `poll_url`.

### `GET /jobs/{job_id}`

`status` is `pending`, `running`, `completed`, `completed_with_errors` or `failed`. `steps` lists each step in order with its own status (`running`, `completed`, `completed_with_errors`, `failed`, `skipped`) and counts such as prices or articles stored. Poll every few seconds until the status is no longer `pending` or `running`.

### `GET /stocks/{ticker}/jobs`

The company's latest refreshes, newest first (`limit` 1–20, default 5). The newest finished one says when its data was last updated.

## Rate limiting

`API_RATE_LIMIT_PER_MINUTE` requests per client IP per minute (default 60; `0` disables). In-memory, per process: fine for one small instance.

## Coming in later phases

`POST /admin/powerbi/refresh` (protected by `ADMIN_API_TOKEN`).
