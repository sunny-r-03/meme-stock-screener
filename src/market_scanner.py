"""Market-wide breakout scanner — find ALL rallies, not a hand-picked list.

The problem: there's no free "list every rallying stock" API. The solution:
bulk-download recent price+volume for the whole ticker universe (yfinance can
fetch hundreds of tickers per call), compute relative volume + recent return
cheaply for all of them, and return only the ones actually breaking out.

The expensive per-ticker data (float, short %, SEC catalyst) is then pulled by
the caller for just these movers — not all 12,000 names.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

from .ticker_universe import load_universe


@dataclass
class Mover:
    symbol: str
    last_close: float
    rvol: float          # today's volume vs 20-day average
    ret_5d: float        # % price change over 5 sessions
    avg_dollar_vol: float  # liquidity proxy (avg volume * price)
    pct_of_high: float   # close / window high (1.0 = at the high)
    closes: list[float] = field(default_factory=list)  # recent closes, for a sparkline


def _scan_chunk(symbols: list[str]) -> list[Mover]:
    """Download one chunk and compute breakout metrics for each ticker."""
    try:
        data = yf.download(
            symbols,
            period="1mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception:
        return []

    movers = []
    for sym in symbols:
        try:
            df = data[sym] if len(symbols) > 1 else data
            close = df["Close"].dropna()
            vol = df["Volume"].dropna()
            if len(close) < 6 or len(vol) < 6:
                continue
            last_close = float(close.iloc[-1])
            close_5_ago = float(close.iloc[-6])
            today_vol = float(vol.iloc[-1])
            avg_vol = float(vol.iloc[:-1].mean())
            window_high = float(close.max())
            if avg_vol <= 0 or last_close <= 0 or window_high <= 0:
                continue
            movers.append(
                Mover(
                    symbol=sym,
                    last_close=round(last_close, 2),
                    rvol=round(today_vol / avg_vol, 2),
                    ret_5d=round((last_close / close_5_ago - 1) * 100, 2),
                    avg_dollar_vol=round(avg_vol * last_close, 0),
                    pct_of_high=round(last_close / window_high, 3),
                    closes=[round(float(x), 2) for x in close.tail(30)],
                )
            )
        except (KeyError, IndexError, TypeError):
            continue
    return movers


def scan_market(
    max_price: float = 50.0,
    min_rvol: float = 2.0,
    min_ret_5d: float = 5.0,
    min_dollar_vol: float = 250_000.0,
    chunk_size: int = 200,
    limit_symbols: int | None = None,
) -> list[Mover]:
    """Scan the universe and return tickers that are breaking out.

    Filters:
      - max_price       keep small/affordable names (where rallies are explosive)
      - min_rvol        unusual volume = something is happening
      - min_ret_5d      already moving up
      - min_dollar_vol  tradeable (not a dead ticker)
    """
    symbols = list(load_universe()["symbol"])
    if limit_symbols:
        symbols = symbols[:limit_symbols]

    results: list[Mover] = []
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        for m in _scan_chunk(chunk):
            if (
                m.last_close <= max_price
                and m.rvol >= min_rvol
                and m.ret_5d >= min_ret_5d
                and m.avg_dollar_vol >= min_dollar_vol
            ):
                results.append(m)

    results.sort(key=lambda m: (m.rvol, m.ret_5d), reverse=True)
    return results
