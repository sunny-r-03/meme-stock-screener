"""SEC EDGAR catalyst signal — the 'reason to buy' driver, free.

A rally needs a catalyst. The richest free source is SEC filings:

  BULLISH catalysts (recent):
    - SC 13D       activist investor took a >5% stake (Ryan Cohen drove BOTH
                   GME and BBBY this way) — the strongest catalyst.
    - SC 13D/A     activist increased/changed stake.
    - SC 13G       large passive stake.
    - 8-K          material corporate event (M&A, new product, leadership).

  DILUTION RISK (recent) — REDUCES rally readiness, because the company can
  print new shares to cap a squeeze:
    - S-1, S-3, S-3/A     registration / shelf offerings
    - 424B3, 424B5        prospectus for an offering

Uses two free, key-less SEC endpoints (a descriptive User-Agent is required):
  - https://www.sec.gov/files/company_tickers.json   (ticker -> CIK map)
  - https://data.sec.gov/submissions/CIK##########.json  (a filer's filings)
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache

import requests

HEADERS = {
    "User-Agent": os.environ.get("SEC_USER_AGENT", "rally-radar/1.0 (contact: you@example.com)"),
    "Accept-Encoding": "gzip, deflate",
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TICKER_MAP_FILE = os.path.join(CACHE_DIR, "sec_ticker_cik.json")

# Disk cache for computed catalyst scores. Filings change slowly, so a daily TTL
# means re-runs and app restarts reuse results instead of re-hitting SEC.
CATALYST_CACHE_FILE = os.path.join(CACHE_DIR, "catalyst_cache.json")
CATALYST_TTL_SECONDS = 24 * 3600
_cache_lock = threading.Lock()  # fetch() runs in worker threads — guard the file
_catalyst_cache: dict | None = None  # lazily loaded {SYM: {score, notes, ok, lookback, ts}}


def _load_catalyst_cache() -> dict:
    global _catalyst_cache
    if _catalyst_cache is None:
        try:
            with open(CATALYST_CACHE_FILE) as fh:
                _catalyst_cache = json.load(fh)
        except Exception:
            _catalyst_cache = {}
    return _catalyst_cache


def _cache_get(symbol: str, lookback_days: int):
    with _cache_lock:
        entry = _load_catalyst_cache().get(symbol)
        if (entry and entry.get("lookback") == lookback_days
                and (time.time() - entry.get("ts", 0)) < CATALYST_TTL_SECONDS):
            return Catalyst(symbol, entry["score"], list(entry.get("notes", [])),
                            ok=entry.get("ok", True))
    return None


def _cache_put(symbol: str, cat: "Catalyst", lookback_days: int) -> None:
    with _cache_lock:
        cache = _load_catalyst_cache()
        cache[symbol] = {"score": cat.score, "notes": cat.notes, "ok": cat.ok,
                         "lookback": lookback_days, "ts": time.time()}
        try:  # atomic write so a crash mid-write can't corrupt the cache
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = CATALYST_CACHE_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(cache, fh)
            os.replace(tmp, CATALYST_CACHE_FILE)
        except Exception:
            pass

# Recent bullish catalysts -> points.
BULLISH = {
    "SC 13D": 40,
    "SC 13D/A": 20,
    "SC 13G": 15,
    "SC 13G/A": 8,
    "8-K": 10,
}
# Recent dilution filings -> penalty points.
DILUTION = {
    "S-1": 25,
    "S-1/A": 15,
    "S-3": 25,
    "S-3/A": 15,
    "424B5": 20,
    "424B3": 15,
}


@dataclass
class Catalyst:
    symbol: str
    score: float                       # 0-100 readiness from filings
    notes: list[str] = field(default_factory=list)
    ok: bool = True


@lru_cache(maxsize=1)
def _ticker_cik_map() -> dict[str, str]:
    """Map UPPER ticker -> 10-digit zero-padded CIK, cached on disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        if os.path.exists(TICKER_MAP_FILE):
            import json
            with open(TICKER_MAP_FILE) as fh:
                return json.load(fh)
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=30
        )
        resp.raise_for_status()
        raw = resp.json()
        out = {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10)
            for row in raw.values()
        }
        import json
        with open(TICKER_MAP_FILE, "w") as fh:
            json.dump(out, fh)
        return out
    except Exception:
        return {}


def _recent_filings(cik: str, lookback_days: int) -> list[tuple[str, str]] | None:
    """Return [(form, filingDate)] filed within lookback_days, or None on a
    transient request failure (so the caller can avoid caching a bad result)."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        recent = resp.json().get("filings", {}).get("recent", {})
    except Exception:
        return None
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    cutoff = datetime.now() - timedelta(days=lookback_days)
    out = []
    for form, date in zip(forms, dates):
        try:
            if datetime.strptime(date, "%Y-%m-%d") >= cutoff:
                out.append((form, date))
        except ValueError:
            continue
    return out


def fetch(symbol: str, lookback_days: int = 120) -> Catalyst:
    """Score recent SEC filings for catalyst strength (minus dilution risk).

    Results are cached to disk (daily TTL) so re-runs and restarts skip the SEC
    round-trip. Transient SEC failures are NOT cached, so they retry next time.
    """
    symbol = symbol.upper()
    cached = _cache_get(symbol, lookback_days)
    if cached is not None:
        return cached

    cik = _ticker_cik_map().get(symbol)
    if not cik:
        result = Catalyst(symbol, 0.0, ["no SEC CIK found"], ok=False)
        _cache_put(symbol, result, lookback_days)  # stable; safe to cache
        return result

    filings = _recent_filings(cik, lookback_days)
    time.sleep(0.12)  # stay well under SEC's 10 req/sec limit
    if filings is None:  # transient failure — return uncached so it retries
        return Catalyst(symbol, 0.0, ["SEC fetch failed (will retry)"], ok=False)

    # Count each form type only ONCE so a pile of routine 8-Ks can't dominate a
    # rare, high-signal activist 13D. We keep the most recent date per form.
    points = 0.0
    penalty = 0.0
    notes: list[str] = []
    seen: set[str] = set()
    for form, date in filings:  # filings are newest-first from SEC
        if form in seen:
            continue
        if form in BULLISH:
            # 8-Ks are routine; only count a recent one as a mild activity signal.
            if form == "8-K":
                days_old = (datetime.now() - datetime.strptime(date, "%Y-%m-%d")).days
                if days_old > 45:
                    continue
            seen.add(form)
            points += BULLISH[form]
            notes.append(f"+{form} ({date})")
        elif form in DILUTION:
            seen.add(form)
            penalty += DILUTION[form]
            notes.append(f"-{form} dilution ({date})")

    score = max(0.0, min(points - penalty, 100.0))
    result = Catalyst(symbol, round(score, 1), notes, ok=True)
    _cache_put(symbol, result, lookback_days)
    return result
