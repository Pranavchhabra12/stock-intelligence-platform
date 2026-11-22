"""Live check against the real Gemini API. Skipped unless RUN_LIVE_TESTS=1 and GEMINI_API_KEY is set."""

from __future__ import annotations

import os

import pytest

from backend.providers.ai.gemini import GeminiClient
from backend.services.ai_analysis import (
    SENTIMENT_SCHEMA,
    SENTIMENT_SYSTEM,
    check_sentiment,
    sentiment_prompt,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call real APIs"),
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY is not set"),
]


def test_gemini_rates_headlines() -> None:
    client = GeminiClient(os.environ["GEMINI_API_KEY"], os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    items = [
        {"company_name": "Infosys", "headline": "Infosys wins $1.5 billion deal from European bank", "snippet": None},
        {"company_name": "HDFC Bank", "headline": "RBI imposes penalty on HDFC Bank for KYC lapses", "snippet": None},
        {"company_name": "TCS", "headline": "TCS board to meet on January 9 to consider results", "snippet": None},
    ]
    got = client.generate_json(SENTIMENT_SYSTEM, sentiment_prompt(items), SENTIMENT_SCHEMA)
    print(f"model={got.model} tokens in/out={got.input_tokens}/{got.output_tokens} legacy={client._legacy_format}")
    by_id = {r["id"]: r for r in got.data["results"]}
    for i, it in enumerate(items):
        print(it["headline"], "->", by_id.get(str(i)))
    assert check_sentiment(by_id["0"])[0] == "positive"
    assert check_sentiment(by_id["1"])[0] == "negative"
    assert check_sentiment(by_id["2"]) is not None
