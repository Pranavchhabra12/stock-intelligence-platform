"""Types shared by news and filing providers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FeedKind = Literal["news", "exchange_filing"]

SNIPPET_MAX = 500  # characters of the publisher's own description we keep

_TRACKING_PARAMS = re.compile(r"^(utm_.*|gclid|fbclid|mc_cid|mc_eid|ref|ref_src|cmpid|from|source|_gl)$", re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class NewsItem:
    source_code: str
    url: str
    headline: str
    snippet: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    kind: FeedKind = "news"


def canonical_url(url: str) -> str:
    """Normalise a URL so the same article is recognised under small variations:
    lower-case scheme and host, no fragment, no tracking parameters, no trailing slash."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def headline_hash(headline: str) -> str:
    """Same story, different URL (syndication): compare normalised headlines."""
    return hashlib.sha256(_NON_ALNUM.sub(" ", headline.lower()).strip().encode()).hexdigest()


def clean_text(value: str | None, limit: int | None = None) -> str | None:
    """Strip HTML tags and extra whitespace; optionally cap the length at a word boundary."""
    if not value:
        return None
    text = _SPACES.sub(" ", _TAGS.sub(" ", value)).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text or None
