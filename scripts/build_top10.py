"""Nightly job: whole-market scan -> data/top10.json.

Run by .github/workflows/daily-top10.yml on a cron after the US close. It does
the heavy lifting (scan ~12k tickers, score the movers) on GitHub's runner and
commits a small JSON file, so the Streamlit app just reads it — instant for
every visitor, and never burns the app's own compute.

Run locally for a quick test:  python scripts/build_top10.py --limit 500
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# Make `src` importable when run as a standalone script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.breakout import Breakout, fetch as fetch_breakout
from src.edgar import fetch as fetch_catalyst
from src.fundamentals import Fundamentals, fetch as fetch_fundamentals
from src.apewisdom import scan as scan_social
from src.market_scanner import scan_all, filter_movers
from src.scoring import build_candidate
from src.display import candidate_row

TOP_N = 10
MAX_MOVERS = 60          # deep-analyze at most this many movers
MAX_WORKERS = 8
DAILY_MAX_CAP_M = 5000   # keep it small/mid-cap focused (the rally sweet spot)

OUT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "top10.json"
)


def _previous_top_symbols() -> set[str]:
    """Yesterday's top-10 symbols, to flag what's newly arrived."""
    try:
        with open(OUT_FILE, encoding="utf-8") as fh:
            return {row["Symbol"] for row in json.load(fh).get("candidates", [])}
    except Exception:
        return set()


def _gather(sym, movers_by_symbol):
    mv = movers_by_symbol.get(sym)
    if mv is not None:
        b = Breakout(sym, mv.rvol, None, mv.ret_5d, mv.pct_of_high, mv.last_close,
                     ok=True, closes=mv.closes)
    else:
        b = fetch_breakout(sym)
    f = fetch_fundamentals(sym)
    cat = fetch_catalyst(sym)
    return sym, b, f, cat


def build(limit_symbols: int | None = None) -> dict:
    print("Pulling social buzz (ApeWisdom)...", flush=True)
    buzz = {b.symbol: b for b in scan_social(flt="all-stocks", pages=2)}
    max_momentum = max((b.momentum for b in buzz.values()), default=1.0)
    print(f"  {len(buzz)} trending tickers.", flush=True)

    print("Scanning the whole market for breakouts...", flush=True)
    all_movers = scan_all(limit_symbols=limit_symbols)
    movers = filter_movers(all_movers, max_price=50, min_rvol=2.5, min_ret_5d=8)[:MAX_MOVERS]
    movers_by_symbol = {m.symbol: m for m in movers}
    print(f"  {len(all_movers)} scanned, {len(movers)} breaking out.", flush=True)

    symbols = list(dict.fromkeys([m.symbol for m in movers] + list(buzz)))
    print(f"Deep-analyzing {len(symbols)} candidates...", flush=True)

    candidates = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_gather, s, movers_by_symbol): s for s in symbols}
        for fut in as_completed(futures):
            sym, b, f, cat = fut.result()
            if not f.ok:
                f = Fundamentals(sym, None, None, b.last_close, None, None, None,
                                 None, None, None, ok=False)
            if f.market_cap and f.market_cap > DAILY_MAX_CAP_M * 1_000_000:
                continue
            candidates.append(build_candidate(
                f, b, buzz.get(sym), max_momentum,
                catalyst=cat.score, catalyst_notes=cat.notes,
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    top = candidates[:TOP_N]

    prev = _previous_top_symbols()
    rows = [candidate_row(c, is_new=c.symbol not in prev) for c in top]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "whole-market",
        "count": len(rows),
        "candidates": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Scan only the first N tickers (for a quick local test).")
    args = ap.parse_args()

    payload = build(limit_symbols=args.limit)
    if not payload["candidates"]:
        # Don't overwrite a good list with an empty one (e.g. a quiet market /
        # rate-limited run). Exit non-zero so the workflow skips the commit.
        print("No candidates produced — leaving existing top10.json untouched.", flush=True)
        return 1

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"Wrote {len(payload['candidates'])} candidates to {OUT_FILE}", flush=True)
    print("Top:", ", ".join(r["Symbol"] for r in payload["candidates"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
