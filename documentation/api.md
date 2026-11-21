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

## Rate limiting

`API_RATE_LIMIT_PER_MINUTE` requests per client IP per minute (default 60; `0` disables). In-memory, per process: fine for one small instance.

## Coming in later phases

`POST /stocks/{ticker}/refresh`, `GET /jobs/{job_id}`, `GET /stocks/{ticker}/prices`, `/financials`, `/news`, `/reports`, `/sentiment`, `/analysis`, and `POST /admin/powerbi/refresh` (protected by `ADMIN_API_TOKEN`).
