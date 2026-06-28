"""Backtest the rally-detection signal against documented historical rallies.

The honest question this answers: 'If I had run this tool the day a famous
rally started, using ONLY data available that day, would it have flagged the
stock — and did a real rally actually follow?'

Method (no lookahead):
  - For each documented event (ticker + ignition date), download daily history.
  - Compute the breakout signal AS OF the ignition date using only prices/volume
    up to and including that day (what we'd have seen at the close).
  - Measure the forward return over the next N trading days (what happened next).

Limitations (stated honestly):
  - Selection bias: these are known winners. A real edge test also needs the
    losers (stocks that lit up and fizzled) — see notes at the bottom.
  - Point-in-time short interest / float aren't free historically, so this
    backtests the PRICE/VOLUME breakout signal precisely; the documented float
    and short interest are shown alongside from the research record.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

from .breakout import Breakout, score as breakout_score

# Documented rally events, given as SEARCH WINDOWS (not hand-picked entry days).
# The tool scans each window for the first day its own breakout trigger fires,
# so the entry is chosen by the rules, not by hindsight. Float/short from record.
EVENTS = [
    # ticker, window_start, window_end, label, documented float, short % of float
    ("GME",  "2021-01-04", "2021-01-29", "GameStop squeeze",        "~50M",  "140%"),
    ("AMC",  "2021-01-04", "2021-01-29", "AMC Jan-2021",            "~450M", "~20%"),
    ("KOSS", "2021-01-04", "2021-01-29", "Koss low-float",          "~2.7M", "high"),
    ("BB",   "2021-01-04", "2021-01-29", "BlackBerry (weak case)",  "~560M", "~7%"),
    ("ATER", "2021-09-01", "2021-10-15", "Aterian low-float",       "~30M",  ">40%"),
    ("GME",  "2024-05-01", "2024-05-31", "GME Roaring Kitty return","~300M", "~20%"),
]

FORWARD_DAYS = 15      # trading days to measure follow-through after entry
TRIGGER_RVOL = 3.0     # unusual volume needed to call it a breakout
TRIGGER_NEAR_HIGH = 0.85  # within 15% of the 60-day high
MAX_RET_5D_ENTRY = 40.0   # GUARD: skip if already up >40% in 5d (too parabolic)


@dataclass
class BacktestRow:
    ticker: str
    label: str
    doc_float: str
    doc_short: str
    entry_date: str | None         # day the tool's trigger first fired
    breakout_score: float
    rvol: float | None
    ret_5d_prior: float | None     # 5-day run INTO the entry (overextension check)
    fwd_max_return: float | None   # best close-to-close gain over next N days
    fwd_end_return: float | None   # gain at the end of the window


def _breakout_asof(hist: pd.DataFrame, idx: int) -> Breakout:
    """Compute the breakout signal as of row `idx`, using only data up to idx."""
    close = hist["Close"]
    vol = hist["Volume"]
    last_close = float(close.iloc[idx])
    prev_close = float(close.iloc[idx - 1])
    close_5_ago = float(close.iloc[idx - 5])

    window_vol = vol.iloc[max(0, idx - 20):idx]   # 20 days BEFORE idx (no lookahead)
    avg_vol = float(window_vol.mean()) if len(window_vol) else 0.0
    today_vol = float(vol.iloc[idx])
    rvol = (today_vol / avg_vol) if avg_vol > 0 else None

    window_close = close.iloc[max(0, idx - 60):idx + 1]
    high_60 = float(window_close.max())

    return Breakout(
        symbol="",
        rvol=round(rvol, 2) if rvol is not None else None,
        ret_1d=round((last_close / prev_close - 1) * 100, 2) if prev_close else None,
        ret_5d=round((last_close / close_5_ago - 1) * 100, 2) if close_5_ago else None,
        pct_of_60d_high=round(last_close / high_60, 3) if high_60 else None,
        last_close=round(last_close, 2),
        ok=True,
    )


def run() -> list[BacktestRow]:
    rows = []
    for ticker, win_start, win_end, label, doc_float, doc_short in EVENTS:
        time.sleep(2)  # avoid yfinance rate limiting
        try:
            start = (pd.Timestamp(win_start) - pd.Timedelta(days=160)).strftime("%Y-%m-%d")
            end = (pd.Timestamp(win_end) + pd.Timedelta(days=45)).strftime("%Y-%m-%d")
            hist = yf.download(
                ticker, start=start, end=end, interval="1d",
                auto_adjust=True, progress=False,
            )
        except Exception:
            hist = None
        if hist is None or hist.empty:
            rows.append(BacktestRow(ticker, label, doc_float, doc_short,
                                    None, 0.0, None, None, None, None))
            continue
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        close = hist["Close"]
        ws, we = pd.Timestamp(win_start), pd.Timestamp(win_end)
        lo = max(hist.index.searchsorted(ws), 25)
        hi = min(hist.index.searchsorted(we) + 1, len(hist))

        # Walk the window; take the FIRST day the trigger fires (rules pick entry).
        entry_pos = None
        for pos in range(lo, hi):
            b = _breakout_asof(hist, pos)
            if (
                b.rvol and b.rvol >= TRIGGER_RVOL
                and (b.pct_of_60d_high or 0) >= TRIGGER_NEAR_HIGH
                and 0 < (b.ret_5d or 0) <= MAX_RET_5D_ENTRY  # early, not parabolic
            ):
                entry_pos = pos
                break

        if entry_pos is None:
            rows.append(BacktestRow(ticker, label, doc_float, doc_short,
                                    "no trigger", 0.0, None, None, None, None))
            continue

        b = _breakout_asof(hist, entry_pos)
        entry = float(close.iloc[entry_pos])
        fwd = close.iloc[entry_pos + 1: entry_pos + 1 + FORWARD_DAYS]
        fwd_max = round((float(fwd.max()) / entry - 1) * 100, 1) if len(fwd) else None
        fwd_end = round((float(fwd.iloc[-1]) / entry - 1) * 100, 1) if len(fwd) else None

        rows.append(BacktestRow(
            ticker, label, doc_float, doc_short,
            hist.index[entry_pos].strftime("%Y-%m-%d"),
            breakout_score(b), b.rvol, b.ret_5d, fwd_max, fwd_end,
        ))
    return rows


if __name__ == "__main__":
    rows = run()
    print(f"\n{'TICKER':6}{'LABEL':26}{'FLOAT':8}{'SHORT':7}{'ENTRY(auto)':13}"
          f"{'RVOL':>6}{'5d-in':>7}{'FWD-MAX':>9}{'FWD-END':>9}")
    print("-" * 100)
    for r in rows:
        print(f"{r.ticker:6}{r.label:26}{r.doc_float:8}{r.doc_short:7}"
              f"{str(r.entry_date):13}{str(r.rvol):>6}{str(r.ret_5d_prior):>7}"
              f"{str(r.fwd_max_return)+'%':>9}{str(r.fwd_end_return)+'%':>9}")
    print(f"\nThe tool picks ENTRY itself (first day RVOL>={TRIGGER_RVOL}, near 60d "
          f"high, NOT already up >{MAX_RET_5D_ENTRY:.0f}% in 5d).")
    print(f"FWD-MAX/END = best / final gain over the next {FORWARD_DAYS} trading days.")
