"""Small-Cap Rally Radar — multipage entry point.

Run with:  streamlit run app.py

Two pages:
  🔍 Live Scanner   — interactive, on-demand rally screener (views/scanner.py)
  🏆 Daily Top 10   — instant pre-computed leaderboard, refreshed nightly by a
                      GitHub Actions job (views/daily_top10.py + scripts/build_top10.py)

Educational tool, NOT financial advice. Most candidates will not rally.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Rally Radar", page_icon="🚀", layout="wide")

scanner = st.Page("views/scanner.py", title="Live Scanner", icon="🔍", default=True)
top10 = st.Page("views/daily_top10.py", title="Daily Top 10", icon="🏆")

st.navigation([scanner, top10]).run()
