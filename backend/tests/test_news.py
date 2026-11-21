"""News: URL handling, feed parsing, GDELT, company matching, collection and the API."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from backend.providers.market_data.base import ProviderError
from backend.providers.news.base import NewsItem, canonical_url, clean_text, headline_hash
from backend.providers.news.gdelt import GdeltNewsAdapter, build_query, parse_seendate
from backend.providers.news.rss import Feed, RssAdapter, parse_feed
from backend.services.company_matcher import CompanyMatcher
from backend.services.news_collector import NewsCollector

NO_SLEEP = lambda _s: None  # noqa: E731
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


# ---------------- URLs and text ----------------

def test_canonical_url_drops_tracking_and_fragments() -> None:
    assert canonical_url("HTTPS://Example.COM/News/Story/?utm_source=x&id=5&fbclid=y#top") == \
        "https://example.com/News/Story?id=5"


def test_headline_hash_ignores_case_and_punctuation() -> None:
    assert headline_hash("Reliance Q2: profit up 10%!") == headline_hash("reliance q2 profit up 10")


def test_clean_text_strips_html_and_caps_length() -> None:
    assert clean_text("<p>Shares <b>rose</b>\n today</p>") == "Shares rose today"
    assert clean_text("word " * 200, limit=20).endswith("…")


# ---------------- RSS ----------------

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Reliance Industries shares hit record</title><link>https://ex.com/a?utm_source=rss</link>
<description><![CDATA[<p>RIL rose 3% on Friday.</p>]]></description>
<pubDate>Fri, 20 Nov 2026 10:30:00 +0530</pubDate></item>
<item><title>No link here</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>TCS wins deal</title><link href="https://ex.com/tcs"/><updated>2026-11-20T08:00:00Z</updated>
<summary>Large contract</summary></entry></feed>"""

FEED = Feed("et_markets_rss", "https://ex.com/feed", "The Economic Times")


def test_parse_rss_and_atom() -> None:
    items = parse_feed(RSS, FEED)
    assert len(items) == 1
    assert items[0].headline == "Reliance Industries shares hit record"
    assert items[0].snippet == "RIL rose 3% on Friday."
    assert items[0].published_at == datetime(2026, 11, 20, 5, 0, tzinfo=UTC)
    atom = parse_feed(ATOM, FEED)
    assert atom[0].url == "https://ex.com/tcs" and atom[0].published_at.year == 2026


def test_hostile_xml_is_refused() -> None:
    bomb = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>
<rss><channel><item><title>&lol2;</title><link>https://x</link></item></channel></rss>"""
    with pytest.raises(ProviderError):
        parse_feed(bomb, FEED)


def test_rss_adapter_reports_blocked_feed() -> None:
    adapter = RssAdapter(client=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(403))),
                         sleep=NO_SLEEP)
    with pytest.raises(ProviderError, match="403"):
        adapter.fetch(FEED)


# ---------------- GDELT ----------------

def test_gdelt_query_and_dates() -> None:
    assert build_query(["Reliance Industries", "Reliance Industries Limited"]) == \
        '("Reliance Industries" OR "Reliance Industries Limited") sourcecountry:india sourcelang:english'
    assert build_query(["Infosys"]) == "Infosys sourcecountry:india sourcelang:english"
    assert parse_seendate("20261120T101500Z") == datetime(2026, 11, 20, 10, 15, tzinfo=UTC)
    assert parse_seendate("garbage") is None


def gdelt_with(handler) -> GdeltNewsAdapter:  # noqa: ANN001
    return GdeltNewsAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)),
                            min_interval_seconds=0, sleep=NO_SLEEP)


def test_gdelt_parses_articles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["mode"] == "ArtList" and request.url.params["format"] == "json"
        return httpx.Response(200, json={"articles": [
            {"url": "https://news.ex/1", "title": "Reliance Industries to expand", "seendate": "20261120T101500Z",
             "domain": "news.ex", "language": "English"},
            {"url": "", "title": "missing url"},
        ]})

    items = gdelt_with(handler).search(["Reliance Industries"])
    assert [i.url for i in items] == ["https://news.ex/1"]
    assert items[0].publisher == "news.ex" and items[0].language == "english"


def test_gdelt_plain_text_error_is_reported() -> None:
    with pytest.raises(ProviderError, match="rejected"):
        gdelt_with(lambda _r: httpx.Response(200, text="Invalid query")).search(["Infosys"])


# ---------------- Company matching ----------------

RIL, HDFC, TCS = uuid4(), uuid4(), uuid4()
MATCHER = CompanyMatcher([
    {"company_id": RIL, "names": ["Reliance Industries"], "other_aliases": ["Reliance"],
     "abbreviations": ["RIL"], "exclude": ["Reliance Power", "Reliance Infrastructure"]},
    {"company_id": HDFC, "names": ["HDFC Bank"], "abbreviations": ["HDFC", "HDFCBANK"], "exclude": ["HDFC Life"]},
    {"company_id": TCS, "names": ["Tata Consultancy Services", "Tata Consultancy"], "abbreviations": ["TCS"]},
])


@pytest.mark.parametrize(("headline", "snippet", "expected"), [
    ("Reliance Industries Q2 profit rises", None, {RIL: (1.0, "headline")}),
    ("RIL shares gain after results", None, {RIL: (0.85, "headline")}),
    ("Reliance Jio adds subscribers", None, {RIL: (0.85, "headline")}),       # subsidiary: still RIL
    ("Reliance Power shares surge", None, {}),                                # a different company
    ("HDFC Life premium grows", None, {}),
    ("Markets close higher", "TCS and HDFC Bank led the gains", {TCS: (0.6, "snippet"), HDFC: (0.6, "snippet")}),
    ("tcs shares", None, {}),                                                  # abbreviations are case-sensitive
    ("April gains for all", None, {}),                                         # "RIL" inside a word doesn't count
])
def test_matcher(headline: str, snippet: str | None, expected: dict) -> None:
    got = {m.company_id: (m.score, m.mention_type) for m in MATCHER.match(headline, snippet)}
    assert got == expected


# ---------------- Collection against the database ----------------

class FakeRss:
    def __init__(self, items_by_feed: dict[str, list[NewsItem]], fail: set[str] = frozenset()) -> None:
        self.items_by_feed, self.fail = items_by_feed, fail

    def fetch(self, feed: Feed) -> list[NewsItem]:
        if feed.source_code in self.fail:
            raise ProviderError(f"{feed.source_code}: HTTP 403")
        return self.items_by_feed.get(feed.source_code, [])


class FakeGdelt:
    def __init__(self, items: list[NewsItem]) -> None:
        self.items, self.calls = items, []

    def search(self, names, timespan="7d", max_records=100):  # noqa: ANN001, ANN201
        self.calls.append((tuple(names), timespan))
        return [i for i in self.items if any(n.lower() in i.headline.lower() or "query" in i.headline for n in names)]


FEEDS = (
    Feed("et_markets_rss", "https://x/et", "The Economic Times"),
    Feed("bse_financial_results", "https://x/bse", "BSE", "exchange_filing"),
)


def item(source: str, url: str, headline: str, snippet: str | None = None) -> NewsItem:
    return NewsItem(source_code=source, url=url, headline=headline, snippet=snippet,
                    publisher="Pub", published_at=datetime(2026, 11, 20, 9, 0, tzinfo=UTC))


def clean_news(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("delete from app.article_companies; delete from app.news_articles; "
                          "delete from app.document_chunks; delete from app.company_documents;"))


@pytest.fixture
def clean(engine: Engine) -> Iterator[None]:
    clean_news(engine)
    yield
    clean_news(engine)


def links(engine: Engine) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(
            """
            select c.company_name, a.headline, ac.relevance_score::float, ac.mention_type
            from app.article_companies ac join app.news_articles a using (article_id)
            join app.companies c using (company_id) order by 1, 2
            """
        ))]


def test_feed_items_are_matched_stored_once_and_unrelated_ones_dropped(engine: Engine, clean: None) -> None:
    rss = FakeRss({"et_markets_rss": [
        item("et_markets_rss", "https://et/1?utm_source=a", "Infosys wins large deal"),
        item("et_markets_rss", "https://et/1?utm_source=b", "Infosys wins large deal"),  # same URL, other tracking
        item("et_markets_rss", "https://et/2", "Gold prices fall"),
    ]})
    result = NewsCollector(engine, rss=rss, feeds=FEEDS, now=NOW).collect()
    assert result.articles_new == 1 and result.duplicates == 1 and result.unmatched_dropped == 1
    assert links(engine) == [("Infosys", "Infosys wins large deal", 0.85, "headline")]


def test_syndicated_copy_under_another_url_is_the_same_story(engine: Engine, clean: None) -> None:
    rss = FakeRss({"et_markets_rss": [
        item("et_markets_rss", "https://et/story", "TCS Q2 results: profit rises 8%"),
        item("et_markets_rss", "https://other.com/tcs-q2", "TCS Q2 Results - Profit Rises 8%"),
    ]})
    result = NewsCollector(engine, rss=rss, feeds=FEEDS, now=NOW).collect()
    assert result.articles_new == 1 and result.duplicates == 1


def test_gdelt_results_without_the_name_get_low_relevance(engine: Engine, clean: None) -> None:
    gdelt = FakeGdelt([
        item("gdelt", "https://g/1", "Reliance Industries signs energy pact"),
        item("gdelt", "https://g/2", "Oil prices and the query economy"),   # returned by the search, no name
    ])
    NewsCollector(engine, gdelt=gdelt, feeds=FEEDS, now=NOW).collect()
    got = {h: (score, mention) for company, h, score, mention in links(engine) if company == "Reliance Industries"}
    assert got["Reliance Industries signs energy pact"] == (1.0, "headline")
    assert got["Oil prices and the query economy"] == (0.4, "query")
    assert dict(gdelt.calls)[("Reliance Industries", "Reliance Industries Limited")] == "1m"  # first run: a month


def test_bse_results_filing_registers_a_document(engine: Engine, clean: None) -> None:
    rss = FakeRss({"bse_financial_results": [
        item("bse_financial_results", "https://bse/att/abc.pdf", "HDFC Bank Ltd - 500180 - Financial Results"),
    ]})
    result = NewsCollector(engine, rss=rss, feeds=FEEDS, now=NOW).collect()
    assert result.documents_registered == 1
    with engine.connect() as conn:
        doc = conn.execute(text("select document_type, extraction_status from app.company_documents")).one()
    assert tuple(doc) == ("quarterly_results", "pending")


def test_one_failing_feed_does_not_stop_the_rest(engine: Engine, clean: None) -> None:
    rss = FakeRss({"bse_financial_results": [item("bse_financial_results", "https://b/1", "Infosys Limited results")]},
                  fail={"et_markets_rss"})
    result = NewsCollector(engine, rss=rss, feeds=FEEDS, now=NOW).collect()
    assert result.status == "completed_with_errors"
    assert result.articles_new == 1


# ---------------- API ----------------

def test_news_api_filters_paginates_and_attributes(client: TestClient, engine: Engine, clean: None) -> None:
    rss = FakeRss({"et_markets_rss": [
        NewsItem("et_markets_rss", f"https://et/{i}", f"Infosys update number {i}", "desc", "The Economic Times",
                 datetime(2026, 11, 1 + i, 9, 0, tzinfo=UTC))
        for i in range(5)
    ]})
    NewsCollector(engine, rss=rss, gdelt=FakeGdelt([item("gdelt", "https://g/q", "query only result")]),
                  feeds=FEEDS, now=NOW).collect()

    page1 = client.get("/stocks/INFY/news", params={"limit": 3}).json()
    assert [a["headline"] for a in page1["articles"]] == [f"Infosys update number {i}" for i in (4, 3, 2)]
    assert page1["articles"][0]["source_attribution"] == "Source: The Economic Times."
    page2 = client.get("/stocks/INFY/news", params={"limit": 3, "before": page1["next_before"]}).json()
    assert [a["headline"] for a in page2["articles"]] == ["Infosys update number 1", "Infosys update number 0"]
    assert page2["next_before"] is None

    everything = client.get("/stocks/INFY/news", params={"min_relevance": 0, "limit": 50}).json()
    assert any(a["mention_type"] == "query" for a in everything["articles"])   # hidden by default, visible at 0


def test_news_api_unknown_ticker(client: TestClient) -> None:
    assert client.get("/stocks/NOSUCHCO/news").status_code == 404
