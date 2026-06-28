"""Small-cap RALLY radar — a long/buy screener.

Run with:  streamlit run app.py

Finds small-cap stocks likely to RALLY (go up) so you can research buying them.
Ranks rally *readiness* from: breakout momentum (volume+price), attention,
small float, and short-interest accelerant. We go long — we never short.

Educational tool, NOT financial advice. Most candidates will not rally.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.breakout import Breakout, fetch as fetch_breakout
from src.edgar import fetch as fetch_catalyst
from src.fundamentals import Fundamentals, fetch as fetch_fundamentals
from src.apewisdom import scan as scan_social
from src.market_scanner import scan_market
from src.scoring import build_candidate, WEIGHTS


def _cached_fundamentals(sym: str) -> Fundamentals:
    """Reuse a successful fundamentals fetch across re-runs to dodge yfinance
    rate limits. Failures are NOT cached, so a re-run retries them."""
    cache = st.session_state.setdefault("fund_cache", {})
    if sym in cache:
        return cache[sym]
    f = fetch_fundamentals(sym)
    if f.ok:
        cache[sym] = f
    return f


def _cached_breakout(sym: str) -> Breakout:
    cache = st.session_state.setdefault("breakout_cache", {})
    if sym in cache:
        return cache[sym]
    b = fetch_breakout(sym)
    if b.ok:
        cache[sym] = b
    return b


def _cached_catalyst(sym: str):
    cache = st.session_state.setdefault("catalyst_cache", {})
    if sym not in cache:
        cache[sym] = fetch_catalyst(sym)
    return cache[sym]


st.set_page_config(page_title="Rally Radar", layout="wide")
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
            for b in scan_social(flt="all-stocks", pages=2):
                buzz_by_symbol[b.symbol] = b
        if buzz_by_symbol:
            st.caption(f"Social: {len(buzz_by_symbol)} trending tickers loaded from ApeWisdom.")
        else:
            st.warning("ApeWisdom returned nothing (network issue) — continuing without social.")

    movers_by_symbol: dict = {}
    if source.startswith("🌎"):
        with st.spinner("Scanning the whole market for breakouts (~3-5 min)..."):
            movers = scan_market(
                max_price=max_price, min_rvol=min_rvol, min_ret_5d=min_ret_5d
            )
        st.success(f"Found {len(movers)} stocks breaking out market-wide.")
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

    # 2) Score each candidate. Fundamentals (yfinance .info) can rate-limit, so
    #    we degrade gracefully: a candidate is kept and scored on whatever data
    #    we DO have (breakout from the market scan never needs a re-fetch).
    candidates = []
    dropped_cap = 0
    no_fundamentals = 0
    prog = st.progress(0.0, text="Pulling data...")
    for i, sym in enumerate(symbols):
        prog.progress((i + 1) / len(symbols), text=f"Analyzing {sym}...")

        # Breakout: reuse the market-scan result if we have it (no extra call).
        mv = movers_by_symbol.get(sym)
        if mv is not None:
            b = Breakout(sym, mv.rvol, None, mv.ret_5d, mv.pct_of_high, mv.last_close, ok=True)
        else:
            b = _cached_breakout(sym)
            if b.ok and b.last_close and b.last_close > max_price:
                continue

        f = _cached_fundamentals(sym)
        if not f.ok:
            no_fundamentals += 1
            f = Fundamentals(sym, None, None, b.last_close, None, None, None, None, None, None, ok=False)
        if f.market_cap and f.market_cap > max_market_cap_m * 1_000_000:
            dropped_cap += 1
            continue

        cat = _cached_catalyst(sym)
        candidates.append(
            build_candidate(
                f, b, buzz_by_symbol.get(sym), max_momentum,
                catalyst=cat.score, catalyst_notes=cat.notes,
            )
        )
    prog.empty()

    if no_fundamentals:
        st.info(f"⚠️ yfinance rate-limited fundamentals for {no_fundamentals} ticker(s) — "
                "those are scored on breakout only (float/short/cap shown as blank). "
                "Re-run in a minute for full data.")

    if not candidates:
        st.warning(f"All {dropped_cap} candidate(s) were above your max market cap "
                   f"(${max_market_cap_m}M). Raise the 'Max market cap' slider.")
        st.stop()

    candidates.sort(key=lambda c: c.score, reverse=True)

    df = pd.DataFrame(
        [
            {
                "Symbol": c.symbol,
                "Name": c.name,
                "Rally Score": c.score,
                "Price": c.last_close,
                "RVOL": c.rvol,
                "5d %": c.ret_5d,
                "Float (M)": round(c.float_shares / 1_000_000, 1) if c.float_shares else None,
                "Mkt Cap ($M)": round(c.market_cap / 1_000_000, 1) if c.market_cap else None,
                "Short %Float": round(c.short_pct_float, 1) if c.short_pct_float else None,
                "Catalyst": c.catalyst_score,
                "Theme Score*": c.theme_score,
                "Themes": ", ".join(c.theme_tags),
                "Reddit mentions": c.mentions,
                "Sector": c.sector,
                # Helper columns (hidden from display) for the 'well-known' filter.
                "_mkt_cap": c.market_cap or 0,
                "_dollar_vol": (c.avg_volume or 0) * (c.last_close or 0),
            }
            for c in candidates
        ]
    )

    display_cols = [col for col in df.columns if not col.startswith("_")]

    # 'Well-known' = bigger + liquid (per the sidebar thresholds).
    known_mask = (
        (df["_mkt_cap"] >= wellknown_min_cap_m * 1_000_000)
        & (df["_dollar_vol"] >= wellknown_min_dollar_vol_m * 1_000_000)
    )

    tab_all, tab_known = st.tabs(
        [f"🏆 All candidates ({len(df)})", f"⭐ Well-known ({int(known_mask.sum())})"]
    )

    with tab_all:
        st.subheader(f"🏆 {len(candidates)} candidates ranked by rally readiness")
        st.caption("RVOL = today's volume vs 20-day avg (>2 = unusual). 5d % = price change over 5 sessions.")
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
        st.bar_chart(df.set_index("Symbol")["Rally Score"])

    with tab_known:
        known = df[known_mask]
        st.subheader(f"⭐ {len(known)} well-known candidates")
        st.caption(
            f"Candidates with market cap ≥ ${wellknown_min_cap_m}M and avg daily "
            f"$ volume ≥ ${wellknown_min_dollar_vol_m}M — recognizable, liquid names. "
            "Tune the thresholds in the sidebar."
        )
        if known.empty:
            st.info("No candidate cleared the 'well-known' thresholds. Household names "
                    "are often larger than this screener's **Max market cap** filter — "
                    "raise that slider (and/or lower the thresholds here) to include them.")
        else:
            st.dataframe(known[display_cols], use_container_width=True, hide_index=True)
            st.bar_chart(known.set_index("Symbol")["Rally Score"])

    st.caption(
        "\\*Theme Score is a **speculative** Emerging-Theme heuristic (R&D-style "
        "growth + margins + theme keywords + attention). It is **not a prediction** "
        "of which products will succeed — expect many false positives. See `src/theme.py`."
    )

    with st.expander("Why these? (catalysts + Reddit context)"):
        for c in candidates[:15]:
            if c.catalyst_notes or c.sample_titles or c.theme_tags:
                st.markdown(f"**{c.symbol}** — score {c.score} (catalyst {c.catalyst_score})")
                if c.theme_tags:
                    st.markdown(f"- 🌱 Theme(s): {', '.join(c.theme_tags)} "
                                f"(speculative score {c.theme_score})")
                for n in c.catalyst_notes:
                    st.markdown(f"- 📄 SEC: {n}")
                for t in c.sample_titles:
                    st.markdown(f"- 💬 {t}")
else:
    st.info("Set your watchlist + filters in the sidebar, then click **Scan for rallies**. "
            "First run downloads the ticker list (~1 min).")
