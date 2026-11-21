"""Live checks against the real news and filing feeds. Skipped unless RUN_LIVE_TESTS=1."""

from __future__ import annotations

import os

import pytest

from backend.providers.market_data.base import ProviderError
from backend.providers.news.gdelt import GdeltNewsAdapter
from backend.providers.news.rss import DEFAULT_FEEDS, RssAdapter, google_news_feed

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call real APIs"),
]


def test_gdelt_finds_reliance_news() -> None:
    items = GdeltNewsAdapter().search(["Reliance Industries"], timespan="7d", max_records=20)
    for i in items[:5]:
        print(f"gdelt: {i.published_at} | {i.publisher} | {i.headline[:90]}")
    assert items


def test_google_news_search_finds_infosys() -> None:
    items = RssAdapter().fetch(google_news_feed(["Infosys"], days=7))
    for i in items[:5]:
        print(f"google news: {i.published_at} | {i.publisher} | {i.headline[:90]}")
    assert items


@pytest.mark.parametrize("feed", DEFAULT_FEEDS, ids=lambda f: f.source_code)
def test_feed_is_reachable_and_parses(feed) -> None:  # noqa: ANN001
    try:
        items = RssAdapter().fetch(feed)
    except ProviderError as exc:
        pytest.fail(f"{feed.source_code}: {exc}")
    print(f"\n{feed.source_code}: {len(items)} items")
    for i in items[:3]:
        print(f"  {i.published_at} | {i.headline[:100]} | {(i.snippet or '')[:120]} | {i.url[:120]}")
    if feed.kind == "exchange_filing":
        # Show the raw shape of exchange feeds; they can be empty outside trading days.
        raw = RssAdapter()._get(feed)
        print("  RAW:", raw[:1500].decode("utf-8", "replace").replace("\n", " "))
    else:
        assert items
