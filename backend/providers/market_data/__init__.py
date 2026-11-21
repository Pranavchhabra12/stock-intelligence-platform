"""Market-data providers. Build them with `build_market_data_provider`."""

from __future__ import annotations

from backend.providers.market_data.base import MarketDataProvider


def get_market_data_provider(code: str, eodhd_api_key: str | None = None) -> MarketDataProvider:
    if code == "yfinance":
        from backend.providers.market_data.yahoo import YahooMarketDataAdapter

        return YahooMarketDataAdapter()
    if code == "upstox":
        from backend.providers.market_data.upstox import UpstoxMarketDataAdapter

        return UpstoxMarketDataAdapter()
    if code == "eodhd":
        if not eodhd_api_key:
            raise ValueError("eodhd needs EODHD_API_KEY")
        from backend.providers.market_data.eodhd import EodhdMarketDataAdapter

        return EodhdMarketDataAdapter(eodhd_api_key)
    raise ValueError(f"Unknown market data provider: {code!r}")


def build_market_data_provider(codes: list[str], eodhd_api_key: str | None = None) -> MarketDataProvider:
    """Providers in priority order, wrapped in a fallback chain.

    EODHD is skipped silently when no API key is configured.
    """
    from backend.providers.market_data.fallback import FallbackMarketDataProvider

    providers = [
        get_market_data_provider(code, eodhd_api_key)
        for code in codes
        if not (code == "eodhd" and not eodhd_api_key)
    ]
    return FallbackMarketDataProvider(providers)
