"""Request ID, request logging and a simple per-client rate limit."""

from __future__ import annotations

import hmac
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from backend.core.errors import error_response
from backend.core.logging import request_id_var

logger = logging.getLogger("backend.request")

RATE_LIMIT_EXEMPT = {"/health", "/docs", "/openapi.json", "/redoc"}


class FixedWindowRateLimiter:
    """In-memory, per-process limiter: N requests per client per 60-second window.

    Good enough for a single small instance. A multi-instance deployment would
    need a shared store (e.g. Redis) instead.
    """

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def check(self, client: str) -> tuple[bool, int]:
        """Return (allowed, seconds_until_reset)."""
        now = int(time.time())
        window = now // 60
        with self._lock:
            if len(self._windows) > 10_000:  # drop stale clients
                self._windows = {k: v for k, v in self._windows.items() if v[0] == window}
            start, count = self._windows.get(client, (window, 0))
            if start != window:
                start, count = window, 0
            count += 1
            self._windows[client] = (start, count)
        return count <= self.limit, 60 - (now % 60)


def _client_id(request: Request) -> str:
    # Render and Vercel put the real client IP first in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


INTERNAL_KEY_HEADER = "x-internal-key"


def install_middleware(app: FastAPI, rate_limit_per_minute: int, internal_api_key: str | None = None) -> None:
    """Request ids, access logs and the per-client rate limit.

    The website renders pages on its own servers, so all its calls share one IP. Those calls
    carry `X-Internal-Key`; when it matches INTERNAL_API_KEY they skip the limit (visitors'
    own browser calls are still limited by their IP)."""
    limiter = FixedWindowRateLimiter(rate_limit_per_minute) if rate_limit_per_minute > 0 else None
    internal = internal_api_key.encode() if internal_api_key else None

    def trusted(request: Request) -> bool:
        given = request.headers.get(INTERNAL_KEY_HEADER)
        return bool(internal and given and hmac.compare_digest(given.encode(), internal))

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            if limiter and request.url.path not in RATE_LIMIT_EXEMPT and not trusted(request):
                allowed, retry_after = limiter.check(_client_id(request))
                if not allowed:
                    response: Response = error_response(
                        429, "rate_limited", "Too many requests. Try again shortly.",
                        headers={"Retry-After": str(retry_after)},
                    )
                    response.headers["X-Request-ID"] = request_id
                    return response
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            return response
        finally:
            request_id_var.reset(token)
