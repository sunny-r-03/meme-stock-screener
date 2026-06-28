"""Volume/price breakout signal — confirms a rally is actually igniting.

This is the single most important 'is it happening NOW' signal. Attention and
short interest tell you a rally is *possible*; volume + price breaking out tell
you buyers are *actually showing up*.

All data is free via yfinance daily history.

Components:
  - RVOL (relative volume): today's volume vs its 20-day average. >2x = unusual.
  - Short-term return: 5-day price change (the rally move itself).
  - Proximity to recent high: breaking to new highs = no overhead supply.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import yfinance as yf


@dataclass
class Breakout:
    symbol: str
    rvol: float | None          # today's volume / 20-day avg volume
    ret_1d: float | None        # % price change, last session
    ret_5d: float | None        # % price change, last 5 sessions
    pct_of_60d_high: float | None  # close / 60-day high (1.0 = at the high)
    last_close: float | None
    ok: bool = True
    closes: list[float] | None = None  # recent daily closes, for a sparkline


def fetch(symbol: str) -> Breakout:
    hist = None
    for attempt in range(4):
        try:
            hist = yf.Ticker(symbol).history(period="3mo", interval="1d")
            break
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if ("rate limit" in msg or "too many requests" in msg) and attempt < 3:
                time.sleep(1.5 * (2 ** attempt))
                continue
            return Breakout(symbol, None, None, None, None, None, ok=False)

    if hist is None or hist.empty or len(hist) < 6:
        return Breakout(symbol, None, None, None, None, None, ok=False)

    close = hist["Close"]
    vol = hist["Volume"]

    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    close_5_ago = float(close.iloc[-6])

    # 20-day average volume, excluding today, to judge today's relative volume.
    avg_vol_20 = float(vol.iloc[-21:-1].mean()) if len(vol) >= 21 else float(vol.iloc[:-1].mean())
    today_vol = float(vol.iloc[-1])
    rvol = (today_vol / avg_vol_20) if avg_vol_20 > 0 else None

    high_60 = float(close.iloc[-60:].max()) if len(close) >= 60 else float(close.max())

    return Breakout(
        symbol=symbol,
        rvol=round(rvol, 2) if rvol is not None else None,
        ret_1d=round((last_close / prev_close - 1) * 100, 2) if prev_close else None,
        ret_5d=round((last_close / close_5_ago - 1) * 100, 2) if close_5_ago else None,
        pct_of_60d_high=round(last_close / high_60, 3) if high_60 else None,
        last_close=round(last_close, 2),
        ok=True,
        closes=[round(float(x), 2) for x in close.tail(30)],
    )


def score(b: Breakout) -> float:
    """0-100 'is a rally igniting right now' score."""
    if not b.ok:
        return 0.0

    # RVOL: 3x average volume or more = max signal.
    rvol_score = min((b.rvol or 0) / 3.0, 1.0) * 100

    # 5-day return: +30% over 5 days = max. Negative returns score 0.
    ret = max(b.ret_5d or 0.0, 0.0)
    momentum_score = min(ret / 30.0, 1.0) * 100

    # Proximity to 60-day high: reward 0.85 -> 1.0+ of the high.
    p = b.pct_of_60d_high or 0.0
    if p >= 1.0:
        high_score = 100.0
    elif p <= 0.85:
        high_score = 0.0
    else:
        high_score = (p - 0.85) / 0.15 * 100

    return round(0.40 * rvol_score + 0.35 * momentum_score + 0.25 * high_score, 1)
