"""Pull free fundamentals for a ticker via yfinance.

We only need the handful of fields that map to the 'GameStop setup':
small market cap, high short interest, recent price action.
"""
from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf


@dataclass
class Fundamentals:
    symbol: str
    name: str | None
    market_cap: float | None
    price: float | None
    short_pct_float: float | None   # % of float sold short (squeeze fuel)
    short_ratio: float | None       # days-to-cover
    float_shares: float | None
    avg_volume: float | None
    week52_change: float | None
    sector: str | None
    ok: bool = True
    # Extra fields for the speculative Emerging-Theme heuristic (see src/theme.py).
    revenue_growth: float | None = None   # YoY revenue growth, %
    gross_margins: float | None = None    # %, a 'scalable product' proxy
    industry: str | None = None
    summary: str | None = None            # longBusinessSummary, scanned for themes


def fetch(symbol: str) -> Fundamentals:
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return Fundamentals(symbol, None, None, None, None, None, None, None, None, None, ok=False)

    short_pct = info.get("shortPercentOfFloat")
    if short_pct is not None:
        short_pct *= 100  # yfinance returns a fraction

    wk52 = info.get("52WeekChange")
    if wk52 is not None:
        wk52 *= 100

    rev_growth = info.get("revenueGrowth")
    if rev_growth is not None:
        rev_growth *= 100  # yfinance returns a fraction

    margins = info.get("grossMargins")
    if margins is not None:
        margins *= 100

    return Fundamentals(
        symbol=symbol,
        name=info.get("shortName") or info.get("longName"),
        market_cap=info.get("marketCap"),
        price=info.get("currentPrice") or info.get("regularMarketPrice"),
        short_pct_float=short_pct,
        short_ratio=info.get("shortRatio"),
        float_shares=info.get("floatShares"),
        avg_volume=info.get("averageVolume"),
        week52_change=wk52,
        sector=info.get("sector"),
        ok=info.get("marketCap") is not None,
        revenue_growth=rev_growth,
        gross_margins=margins,
        industry=info.get("industry"),
        summary=info.get("longBusinessSummary"),
    )
