"""🏆 Daily Top 10 page — instant, pre-computed leaderboard.

This page does NO live scanning. A nightly GitHub Actions job (see
scripts/build_top10.py + .github/workflows/daily-top10.yml) runs the
whole-market scan after the US close and commits data/top10.json. Every visitor
just reads that file, so the page loads instantly and is identical for everyone.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.display import column_config, display_columns, render_results

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "top10.json")

st.title("🏆 Daily Top 10")
st.caption(
    "The 10 highest **rally-readiness** candidates from last night's whole-market "
    "scan. Refreshes automatically every day after the US market close — so it's "
    "instant for everyone. **Educational only — not financial advice.**"
)


def _load() -> dict | None:
    try:
        with open(DATA_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _freshness(generated_at: str | None) -> None:
    if not generated_at:
        return
    try:
        gen = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        st.caption(f"Generated: {generated_at}")
        return
    age = datetime.now(timezone.utc) - gen
    hours = age.total_seconds() / 3600
    stamp = gen.strftime("%Y-%m-%d %H:%M UTC")
    if hours < 36:
        st.success(f"✅ Updated {stamp} ({hours:.0f}h ago).")
    else:
        st.warning(f"⚠️ List is stale — last updated {stamp} ({age.days}d ago). "
                   "The nightly job may not have run. Use the 🔍 Live Scanner for fresh data.")


payload = _load()

if not payload or not payload.get("candidates"):
    st.info(
        "The Daily Top 10 hasn't been generated yet. It appears after the first "
        "nightly run (every day ~1am ET). In the meantime, open the **🔍 Live "
        "Scanner** from the sidebar to scan right now."
    )
    st.stop()

_freshness(payload.get("generated_at"))

df = pd.DataFrame(payload["candidates"])
render_results(df[display_columns(df)], key="top10")

with st.expander("ℹ️ How this list is built"):
    st.markdown(
        "Each night after the US close, a background job scans **every** US-listed "
        "ticker for breakouts (unusual volume + rising price near recent highs), "
        "scores the movers with the full **Rally Score** (breakout + social buzz + "
        "SEC catalyst + small float + short interest), and keeps the top 10.\n\n"
        "It's a **daily snapshot**, not live tick-by-tick data. For an on-demand "
        "scan with your own filters, use the **🔍 Live Scanner** page.\n\n"
        "🆕 marks names that weren't in the previous day's top 10."
    )
