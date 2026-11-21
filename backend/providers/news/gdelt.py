"""GDELT DOC 2.0 article search: free, keyless news discovery.

Returns headline, URL, domain, language and the time GDELT first saw the
article. It has no article text. Searches cover a rolling window of about three
months. GDELT asks for roughly one request every five seconds, and on a bad
query it may answer with plain text (even with HTTP 200), which is treated as
an error.

Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import httpx

from backend.providers.market_data.base import ProviderError
from backend.providers.news.base import NewsItem, clean_text
from backend.providers.retry import CallPolicy

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# GDELT titles come tokenised: "RIL , SAIL ( up 3 % )". Undo the extra spaces.
_SPACE_BEFORE = re.compile(r"\s+([,.:;!?%)\]])")
_SPACE_AFTER = re.compile(r"([(\[])\s+")
_SPLIT_DECIMAL = re.compile(r"(\d)\. (\d)")                    # "1. 55" -> "1.55"
_SPLIT_DOMAIN = re.compile(r"\. (com|in|org|net|co|news)\b")    # "Example. com" -> "Example.com"


def tidy_title(title: str | None) -> str | None:
    cleaned = clean_text(title)
    if not cleaned:
        return None
    cleaned = _SPACE_AFTER.sub(r"\1", _SPACE_BEFORE.sub(r"\1", cleaned))
    return _SPLIT_DOMAIN.sub(r".\1", _SPLIT_DECIMAL.sub(r"\1.\2", cleaned))
MAX_RECORDS = 250


def build_query(names: Sequence[str], country: str = "india", language: str = "english") -> str:
    """'("Reliance Industries" OR "RIL") sourcecountry:india sourcelang:english'"""
    terms = [f'"{n}"' if " " in n else n for n in dict.fromkeys(names) if n]
    if not terms:
        raise ValueError("at least one search name is required")
    joined = terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"
    return f"{joined} sourcecountry:{country} sourcelang:{language}"


def parse_seendate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


class GdeltNewsAdapter:
    source_code = "gdelt"

    def __init__(
        self, client: httpx.Client | None = None, min_interval_seconds: float = 10.0, max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep, backoff_seconds: float = 20.0,
    ) -> None:
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": "stock-intelligence-platform"})
        # GDELT asks for at most one request every 5 seconds and answers 429 when busy,
        # so requests are spaced 10s apart and retries wait 20s, then 40s.
        self.policy = CallPolicy(self.source_code, min_interval_seconds, max_attempts, sleep,
                                 backoff_base=backoff_seconds)

    def _fetch(self, query: str, timespan: str, max_records: int) -> dict:
        response = self.client.get(API_URL, params={
            "query": query, "mode": "ArtList", "format": "json", "sort": "DateDesc",
            "maxrecords": str(min(max_records, MAX_RECORDS)), "timespan": timespan,
        })
        response.raise_for_status()
        if not response.content.strip():
            return {}
        try:
            return response.json()
        except ValueError:
            # GDELT reports query errors as plain text.
            raise ProviderError(f"gdelt rejected the query: {response.text[:200]}") from None

    def search(self, names: Sequence[str], timespan: str = "7d", max_records: int = 100) -> list[NewsItem]:
        query = build_query(names)
        payload = self.policy.call("search", query, lambda: self._fetch(query, timespan, max_records))
        items = []
        for art in payload.get("articles", []) or []:
            url, title = art.get("url"), tidy_title(art.get("title"))
            if not url or not title:
                continue
            items.append(NewsItem(
                source_code=self.source_code, url=url, headline=title,
                publisher=art.get("domain") or None, published_at=parse_seendate(art.get("seendate")),
                language=(art.get("language") or "").lower() or None,
            ))
        return items
