"""RSS / Atom feeds: publisher news feeds and BSE's official filing feeds.

Feeds are parsed with defusedxml, which refuses entity-expansion and
external-entity tricks that a hostile feed could use against a plain XML
parser. Only the headline, link, date and the feed's own short description are
kept; article bodies are never fetched.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree as SafeET

from backend.providers.market_data.base import ProviderError
from backend.providers.news.base import SNIPPET_MAX, FeedKind, NewsItem, clean_text
from backend.providers.retry import CallPolicy

_ATOM = "{http://www.w3.org/2005/Atom}"
# BSE filing titles look like "Maruti Suzuki India Ltd (532500)".
_BSE_TITLE = re.compile(r"^(?P<company>.+?)\s*\((?P<code>\d{6})\)\s*$")
# Some BSE feeds put the date in the description: "AS ON DATE : 22-Nov-2026".
_BSE_AS_ON = re.compile(r"AS ON DATE\s*:\s*(?P<date>\d{1,2}-[A-Za-z]{3}-\d{4})", re.I)


@dataclass(frozen=True)
class Feed:
    source_code: str     # matches app.data_sources.source_code
    url: str
    publisher: str
    kind: FeedKind = "news"
    #: for exchange feeds whose items carry no subject (e.g. "Annual report")
    label: str | None = None


# Verified feed URLs (see documentation/decisions.md). Order does not matter.
DEFAULT_FEEDS: tuple[Feed, ...] = (
    Feed("et_markets_rss", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
         "The Economic Times"),
    Feed("et_stocks_rss", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
         "The Economic Times"),
    Feed("mint_markets_rss", "https://www.livemint.com/rss/markets", "Mint"),
    Feed("mint_companies_rss", "https://www.livemint.com/rss/companies", "Mint"),
    Feed("bse_announcements", "https://beta.bseindia.com/data/xml/announcements.xml", "BSE", "exchange_filing"),
    Feed("bse_financial_results", "https://www.bseindia.com/Data/XML/FinancialResultsFeed.aspx", "BSE",
         "exchange_filing", "Financial results"),
    Feed("bse_annual_reports", "https://www.bseindia.com/Data/XML/AnnualReportFeed.aspx", "BSE", "exchange_filing",
         "Annual report"),
)


def _text(el: Element | None) -> str | None:
    return el.text.strip() if el is not None and el.text else None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for parse in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            parsed = parse(value.strip())
        except (TypeError, ValueError):
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _shape_exchange_item(item: NewsItem, feed: Feed) -> NewsItem:
    """BSE items: title = "Company (code)", description = subject. Build a readable headline,
    keep the scrip code for exact matching, and read the date from the description if present."""
    m = _BSE_TITLE.match(item.headline)
    if not m:
        return item
    subject = item.snippet or ""
    published = item.published_at
    as_on = _BSE_AS_ON.search(subject)
    if as_on:
        try:
            published = datetime.strptime(as_on["date"], "%d-%b-%Y").replace(tzinfo=UTC)
        except ValueError:
            pass
        subject = ""
    subject = subject or feed.label or "Exchange filing"
    return NewsItem(
        source_code=item.source_code, url=item.url, headline=f"{m['company']}: {subject}"[:1000],
        snippet=None, publisher=item.publisher, published_at=published, language=item.language,
        kind=item.kind, exchange_code=m["code"],
    )


def parse_feed(xml: bytes, feed: Feed) -> list[NewsItem]:
    try:
        root = SafeET.fromstring(xml)
    except Exception as exc:  # noqa: BLE001 - defusedxml raises several types
        raise ProviderError(f"{feed.source_code}: not a readable feed ({type(exc).__name__})") from None

    items: list[NewsItem] = []
    for item in root.iter("item"):  # RSS 2.0
        link, title = _text(item.find("link")), clean_text(_text(item.find("title")))
        if link and title:
            items.append(NewsItem(
                source_code=feed.source_code, url=link, headline=title, publisher=feed.publisher, kind=feed.kind,
                snippet=clean_text(_text(item.find("description")), SNIPPET_MAX),
                published_at=_parse_date(_text(item.find("pubDate"))),
            ))
    for entry in root.iter(f"{_ATOM}entry"):  # Atom
        link_el = entry.find(f"{_ATOM}link")
        link = link_el.get("href") if link_el is not None else None
        title = clean_text(_text(entry.find(f"{_ATOM}title")))
        if link and title:
            items.append(NewsItem(
                source_code=feed.source_code, url=link, headline=title, publisher=feed.publisher, kind=feed.kind,
                snippet=clean_text(_text(entry.find(f"{_ATOM}summary")), SNIPPET_MAX),
                published_at=_parse_date(_text(entry.find(f"{_ATOM}updated"))
                                         or _text(entry.find(f"{_ATOM}published"))),
            ))
    if feed.kind == "exchange_filing":
        items = [_shape_exchange_item(i, feed) for i in items]
    return items


class RssAdapter:
    MAX_BYTES = 5_000_000

    def __init__(
        self, client: httpx.Client | None = None, max_attempts: int = 2, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=20, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; stock-intelligence-platform; educational project)"},
        )
        self.max_attempts = max_attempts
        self.sleep = sleep

    def _get(self, feed: Feed) -> bytes:
        response = self.client.get(feed.url)
        if response.status_code in (401, 403, 404, 410):
            raise ProviderError(f"{feed.source_code}: HTTP {response.status_code}")
        response.raise_for_status()
        if len(response.content) > self.MAX_BYTES:
            raise ProviderError(f"{feed.source_code}: feed larger than {self.MAX_BYTES} bytes")
        return response.content

    def fetch(self, feed: Feed) -> list[NewsItem]:
        policy = CallPolicy(feed.source_code, 0.5, self.max_attempts, self.sleep)
        return parse_feed(policy.call("feed", feed.url, lambda: self._get(feed)), feed)
