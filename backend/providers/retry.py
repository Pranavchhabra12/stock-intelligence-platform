"""Request spacing and retries shared by every external provider."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from backend.providers.market_data.base import ProviderError, ProviderUnavailableError

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CallPolicy:
    """Waits at least `min_interval` seconds between calls and retries failures
    with exponential back-off (backoff_base x 1, 2, 4...). A `ProviderError` raised inside the
    call is final (e.g. "symbol not found") and is not retried."""

    def __init__(
        self, source_code: str, min_interval: float = 1.0, max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep, backoff_base: float = 1.0,
    ) -> None:
        self.source_code = source_code
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self._sleep = sleep
        self.backoff_base = backoff_base
        self._last_call = 0.0

    def call(self, what: str, subject: str, fn: Callable[[], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            try:
                return fn()
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 - network and parsing errors are retried
                last_error = exc
                logger.warning(
                    "provider_call_failed",
                    extra={"provider": self.source_code, "call": what, "subject": subject,
                           "attempt": attempt, "error": str(exc)[:200]},
                )
                if attempt < self.max_attempts:
                    self._sleep(self.backoff_base * 2 ** (attempt - 1))
        raise ProviderUnavailableError(
            f"{self.source_code} {what} for {subject} failed after {self.max_attempts} attempts"
        ) from last_error
