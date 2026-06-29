"""🔍 Live Scanner page — the interactive rally screener.

Finds small-cap stocks likely to RALLY (go up) so you can research buying them.
Ranks rally *readiness* from: breakout momentum (volume+price), attention,
small float, and short-interest accelerant. We go long — we never short.

Educational tool, NOT financial advice. Most candidates will not rally.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.breakout import Breakout, fetch as fetch_breakout
from src.edgar import Catalyst, fetch as fetch_catalyst
from src.fundamentals import Fundamentals, fetch as fetch_fundamentals
from src.apewisdom import scan as scan_social
from src.market_scanner import scan_all, filter_movers
from src.scoring import build_candidate, WEIGHTS
from src.display import candidate_row, display_columns, render_results

# Deep-analysis is pure network I/O, so fetch tickers concurrently. Kept modest
# to stay friendly to yfinance/SEC rate limits while still cutting wall-clock.
MAX_WORKERS = 8


@st.cache_data(ttl=300, show_spinner=False)
def _social_buzz(pages: int = 2):
    """ApeWisdom buzz, cached 5 min so re-running a scan doesn't re-pull it."""
    return scan_social(flt="all-stocks", pages=pages)


@st.cache_data(ttl=600, show_spinner=False)
def _all_movers():
    """The whole-market breakout download, cached 10 min. Filtering by the user's
    sliders happens in-memory afterward, so slider tweaks don't re-download."""
    return scan_all()


# Process-global per-ticker cache (lives in the app process, SHARED across all
# user sessions and reruns — so a full session reset still re-scans in seconds,
# not minutes). Thread-safe, so the worker threads can use it directly. Only
# successful fetches are cached; entries expire after _CACHE_TTL.
_CACHE_TTL = 900  # 15 minutes — fresh enough for intraday, avoids re-hammering APIs
_cache_lock = threading.Lock()
_fund_cache: dict = {}      # sym -> (timestamp, Fundamentals)
_breakout_cache: dict = {}  # sym -> (timestamp, Breakout)


def _cached(cache: dict, sym: str, fetch_fn):
    now = time.time()
    with _cache_lock:
        hit = cache.get(sym)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    result = fetch_fn(sym)
    if getattr(result, "ok", False):
        with _cache_lock:
            cache[sym] = (now, result)
    return result


def _gather(sym, movers_by_symbol, use_catalyst):
    """Fetch all per-ticker signals for one symbol. Thread-safe: the caches it
    touches are process-global and lock-guarded, so it's safe in a worker thread
    and its results survive session resets. Catalyst is disk-cached in edgar.py."""
    mv = movers_by_symbol.get(sym)
    if mv is not None:  # reuse the market-scan breakout — no extra network call
        b = Breakout(sym, mv.rvol, None, mv.ret_5d, mv.pct_of_high, mv.last_close,
                     ok=True, closes=mv.closes)
    else:
        b = _cached(_breakout_cache, sym, fetch_breakout)
    f = _cached(_fund_cache, sym, fetch_fundamentals)
    cat = Catalyst(sym, 0.0, [], ok=False) if not use_catalyst else fetch_catalyst(sym)
    return sym, b, f, cat


LAST_SCAN_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "last_scan.json")


def _save_last_scan(scan: dict) -> None:
    """Persist the last scan to disk so a hard refresh / reopen reloads it
    instantly (no re-scan). JSON-clean: `records`/`explain` hold only plain
    dicts. Best-effort — a write failure never breaks the scan."""
    try:
        os.makedirs(os.path.dirname(LAST_SCAN_FILE), exist_ok=True)
        tmp = LAST_SCAN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(scan, fh)
        os.replace(tmp, LAST_SCAN_FILE)
    except Exception:
        pass


def _load_last_scan() -> dict | None:
    try:
        with open(LAST_SCAN_FILE, encoding="utf-8") as fh:
            scan = json.load(fh)
        return scan if scan.get("records") else None
    except Exception:
        return None


def _render_scan(scan: dict, wk_cap_m: float, wk_vol_m: float) -> None:
    """Render a stored scan result from plain dicts (so it works whether the scan
    came from this session OR was reloaded from disk on refresh/reopen). Repaints
    on ANY rerun without re-scanning — results don't vanish when the page reloads."""
    df = pd.DataFrame(scan["records"])
    explain = scan.get("explain", [])
    display_cols = display_columns(df)

    when = scan.get("generated_at", "")
    st.caption(f"🕒 Showing the most recent scan ({scan['n']} candidates"
               + (f", run {when} UTC" if when else "")
               + "). Loads instantly on refresh — click **Scan for rallies** to run a fresh one.")
    if scan["no_fundamentals"]:
        st.info(f"⚠️ yfinance rate-limited fundamentals for {scan['no_fundamentals']} ticker(s) — "
                "those are scored on breakout only (float/short/cap blank). Re-scan for full data.")

    # Well-known filter re-applies live from the current sliders (no re-scan).
    known_mask = (
        (df["_mkt_cap"] >= wk_cap_m * 1_000_000)
        & (df["_dollar_vol"] >= wk_vol_m * 1_000_000)
    )
    tab_all, tab_known = st.tabs(
        [f"🏆 All candidates ({len(df)})", f"⭐ Well-known ({int(known_mask.sum())})"]
    )
    with tab_all:
        st.caption("RVOL = today's volume vs 20-day avg (>2 = unusual). 5d % = price change over 5 sessions. "
                   "Click any column header to sort.")
        if scan["first_scan"]:
            st.caption("ℹ️ First scan this session — 🆕 'new' flags appear from your next scan onward.")
        render_results(df[display_cols], key="all")
    with tab_known:
        known = df[known_mask]
        st.caption(
            f"Candidates with market cap ≥ ${wk_cap_m}M and avg daily $ volume ≥ "
            f"${wk_vol_m}M — recognizable, liquid names. Tune the thresholds in the sidebar."
        )
        if known.empty:
            st.info("No candidate cleared the 'well-known' thresholds. Household names "
                    "are often larger than this screener's **Max market cap** filter — "
                    "raise that slider (and/or lower the thresholds here) to include them.")
        else:
            render_results(known[display_cols], key="known")

    st.caption(
        "\\*Theme Score is a **speculative** Emerging-Theme heuristic (R&D-style "
        "growth + margins + theme keywords + attention). It is **not a prediction** "
        "of which products will succeed — expect many false positives. See `src/theme.py`."
    )
    with st.expander("Why these? (catalysts + Reddit context)"):
        for e in explain:
            if e.get("catalyst_notes") or e.get("sample_titles") or e.get("theme_tags"):
                st.markdown(f"**{e['symbol']}** — score {e['score']} (catalyst {e['catalyst_score']})")
                if e.get("theme_tags"):
                    st.markdown(f"- 🌱 Theme(s): {', '.join(e['theme_tags'])} "
                                f"(speculative score {e['theme_score']})")
                for n in e.get("catalyst_notes", []):
                    st.markdown(f"- 📄 SEC: {n}")
                for t in e.get("sample_titles", []):
                    st.markdown(f"- 💬 {t}")


st.title("🚀 Small-Cap Rally Radar")
st.caption(
    "Ranks small-cap stocks by how ready they look to **rally (go up)** — "
    "breakout momentum + attention + thin float + short-interest fuel. "
    "We go long, never short. **Educational only — not financial advice.**"
)

with st.expander("📊 How the Rally Score is calculated (full details)"):
    w = WEIGHTS
    st.markdown(f"""
The **Rally Score** is a 0–100 blend of six signals. Each signal is scored 0–100
on its own, then combined with these weights (they sum to 1.0):

| Signal | Weight | What it measures | How it's scored (0–100) |
|---|---|---|---|
| **Breakout** | {w['breakout']:.0%} | Is a rally igniting *now*? | See breakdown below |
| **Social / attention** | {w['social']:.0%} | Is a crowd forming? | This ticker's ApeWisdom *momentum* ÷ the highest momentum seen this scan |
| **Catalyst** | {w['catalyst']:.0%} | Is there a concrete reason to buy? | SEC EDGAR scan: **+** activist stakes (SC 13D) & recent 8-Ks; **−** dilution filings (S-1/S-3/424B) |
| **Small float** | {w['smallfloat']:.0%} | *Accelerant* — thin float amplifies buying | ≤8M shares = 100, decaying to 0 by ~150M shares (falls back to market cap if float missing) |
| **Short interest** | {w['short']:.0%} | *Accelerant* — trapped shorts must buy | % of float short ÷ 20% (20%+ short = max). We BUY these, never short them |
| **Liquidity** | {w['liquidity']:.0%} | Tradeable sanity check | <50k avg vol = 20, >50M = 40, in-between = 100 |

**Breakout sub-score** (the most important "is it happening now" signal) is itself
a blend:
- **40%** Relative Volume (RVOL): today's volume ÷ 20-day average. 3× = max.
- **35%** 5-day return: price change over 5 sessions. +30% = max. Negative = 0.
- **25%** Proximity to 60-day high: rewards 0.85 → 1.0+ of the recent high (new highs = no overhead supply).

**Overextension guard:** a stock already up **>40% in 5 days** gets its score
*dampened* (down to ~0.4× by +120%). Buying a confirmed parabolic move is a
chase, not an entry — this lost 70%+ in backtests.

---

**🌱 Theme Score** is shown as a **separate** column and is **NOT** part of the
Rally Score. It's a *speculative* heuristic (theme keyword tags + revenue growth
+ gross margin + attention) and is **not a prediction** of which products will
succeed. Expect many false positives.

> ⚠️ This ranks rally *readiness* — it does **not** predict prices. Most
> candidates will not rally. Educational tool, not financial advice.
""")

DEFAULT_WATCHLIST = "KOSS, GME, AMC, BBBY, ATER, PROG, BB, SPRT, IRNT"

with st.sidebar:
    st.header("Candidate source")
    source = st.radio(
        "Where should candidates come from?",
        ["🌎 Whole market (find all rallies)", "📝 My watchlist"],
        index=0,
    )
    watchlist_raw = st.text_area(
        "Watchlist tickers (comma-separated)", DEFAULT_WATCHLIST, height=80,
        disabled=source.startswith("🌎"),
    )
    use_social = st.checkbox("Fold in social buzz (ApeWisdom — no setup)", value=True)
    add_trending = st.checkbox("Also treat trending social tickers as candidates", value=True)
    use_catalyst = st.checkbox("Scan SEC for catalysts (slower)", value=True,
                               help="Uncheck for a faster scan — skips the SEC EDGAR "
                                    "filing lookups (Catalyst column shows 0).")

    st.header("Filters")
    max_market_cap_m = st.slider("Max market cap ($M)", 50, 50_000, 1000, step=50)
    st.caption("Tip: well-known names run big — GME is ~$10B. Raise this to include them.")
    max_price = st.slider("Max share price ($)", 1, 200, 50)
    st.caption("Market-scan breakout thresholds:")
    min_rvol = st.slider("Min relative volume (RVOL)", 1.5, 10.0, 2.5, step=0.5)
    min_ret_5d = st.slider("Min 5-day gain (%)", 0, 50, 8)
    max_movers = st.slider("Max movers to deep-analyze", 20, 150, 60, step=10)

    st.header("⭐ 'Well-known' tab")
    st.caption("Defines which candidates count as well-known (bigger + liquid). "
               "Raise 'Max market cap' above to let large household names through.")
    wellknown_min_cap_m = st.slider("Min market cap ($M)", 50, 50_000, 300, step=50)
    wellknown_min_dollar_vol_m = st.slider("Min avg daily $ volume ($M)", 0.0, 50.0, 1.0, step=0.5)
    run = st.button("🔍 Scan for rallies", type="primary")

if run:
    # 1) Build candidate ticker set.
    buzz_by_symbol: dict = {}
    if use_social:
        with st.spinner("Pulling social buzz from ApeWisdom..."):
            for b in _social_buzz(pages=2):
                buzz_by_symbol[b.symbol] = b
        if buzz_by_symbol:
            st.caption(f"Social: {len(buzz_by_symbol)} trending tickers loaded from ApeWisdom.")
        else:
            st.warning("ApeWisdom returned nothing (network issue) — continuing without social.")

    movers_by_symbol: dict = {}
    if source.startswith("🌎"):
        with st.spinner("Scanning the whole market for breakouts (first run ~1-2 min, then cached)..."):
            all_movers = _all_movers()  # cached 10 min — only the first run pays
        movers = filter_movers(
            all_movers, max_price=max_price, min_rvol=min_rvol, min_ret_5d=min_ret_5d
        )
        st.success(f"Found {len(movers)} breaking out (filtered from {len(all_movers)} "
                   "scanned market-wide; re-filtering is instant for 10 min).")
        movers = movers[:max_movers]
        movers_by_symbol = {m.symbol: m for m in movers}
        social_extra = list(buzz_by_symbol) if add_trending else []
        symbols = [m.symbol for m in movers] + social_extra
    else:
        watchlist = [t.strip().upper() for t in watchlist_raw.split(",") if t.strip()]
        social_extra = list(buzz_by_symbol) if add_trending else []
        symbols = list(dict.fromkeys(watchlist + social_extra))

    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        st.warning("No candidate tickers found. Loosen the breakout filters or add a watchlist.")
        st.stop()

    max_momentum = max((b.momentum for b in buzz_by_symbol.values()), default=1.0)

    # 2) Fetch every candidate's signals CONCURRENTLY (pure network I/O), then
    #    assemble on the main thread. Caching lives inside _gather (process-global,
    #    survives session resets). yfinance .info can rate-limit, so we degrade
    #    gracefully: a candidate is kept and scored on whatever data we DO have.
    fetched: dict = {}
    prog = st.progress(0.0, text="Pulling data...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_gather, s, movers_by_symbol, use_catalyst): s
            for s in symbols
        }
        for done, fut in enumerate(as_completed(futures)):
            sym, b, f, cat = fut.result()
            fetched[sym] = (b, f, cat)
            prog.progress((done + 1) / len(symbols), text=f"Analyzed {done + 1}/{len(symbols)}...")
    prog.empty()

    # Assemble candidates in the original symbol order, applying filters.
    candidates = []
    dropped_cap = 0
    no_fundamentals = 0
    for sym in symbols:
        b, f, cat = fetched[sym]
        if movers_by_symbol.get(sym) is None and b.ok and b.last_close and b.last_close > max_price:
            continue
        if not f.ok:
            no_fundamentals += 1
            f = Fundamentals(sym, None, None, b.last_close, None, None, None, None, None, None, ok=False)
        if f.market_cap and f.market_cap > max_market_cap_m * 1_000_000:
            dropped_cap += 1
            continue
        candidates.append(
            build_candidate(
                f, b, buzz_by_symbol.get(sym), max_momentum,
                catalyst=cat.score, catalyst_notes=cat.notes,
            )
        )

    if no_fundamentals:
        st.info(f"⚠️ yfinance rate-limited fundamentals for {no_fundamentals} ticker(s) — "
                "those are scored on breakout only (float/short/cap shown as blank). "
                "Re-run in a minute for full data.")

    if not candidates:
        st.warning(f"All {dropped_cap} candidate(s) were above your max market cap "
                   f"(${max_market_cap_m}M). Raise the 'Max market cap' slider.")
        st.stop()

    candidates.sort(key=lambda c: c.score, reverse=True)

    # 'New since last scan' — diff this scan's symbols against the previous one
    # (this session). First scan has no baseline, so nothing is flagged new.
    current_symbols = {c.symbol for c in candidates}
    prev_symbols = st.session_state.get("prev_scan_symbols")
    new_symbols = (current_symbols - prev_symbols) if prev_symbols else set()
    first_scan = prev_symbols is None
    st.session_state["prev_scan_symbols"] = current_symbols

    # Build JSON-clean payload (plain dicts) so the SAME structure works for
    # in-session re-rendering AND disk persistence across refresh/reopen.
    records = [candidate_row(c, is_new=c.symbol in new_symbols) for c in candidates]
    explain = [
        {
            "symbol": c.symbol, "score": c.score, "catalyst_score": c.catalyst_score,
            "theme_tags": c.theme_tags, "theme_score": c.theme_score,
            "catalyst_notes": c.catalyst_notes, "sample_titles": c.sample_titles,
        }
        for c in candidates[:15]
    ]
    scan = {
        "records": records,
        "explain": explain,
        "n": len(candidates),
        "no_fundamentals": no_fundamentals,
        "first_scan": first_scan,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    }
    st.session_state["scan"] = scan   # survives reruns (tab switch, reconnect)
    _save_last_scan(scan)             # survives hard refresh / reopen

# Render the most recent scan on EVERY rerun (so results don't vanish when the
# Scan button resets to False). On a fresh session (refresh/reopen) there's no
# session scan, so fall back to the last scan persisted on disk — instant load.
scan = st.session_state.get("scan") or _load_last_scan()
if scan is None:
    st.info("Set your watchlist + filters in the sidebar, then click **Scan for rallies**. "
            "First run downloads the ticker list (~1 min).")
    st.markdown("👉 Want results right now? See the pre-computed leaderboard:")
    st.page_link("views/daily_top10.py", label="🏆 Daily Top 10", icon="🏆")
else:
    st.session_state.setdefault("scan", scan)
    _render_scan(scan, wellknown_min_cap_m, wellknown_min_dollar_vol_m)
