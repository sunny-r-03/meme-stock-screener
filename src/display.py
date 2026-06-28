"""Shared presentation layer — one definition of a result row + table styling.

Used by the live scanner page, the Daily Top 10 page, AND the nightly build
script, so the columns/formatting never drift between them. `candidate_row` is
pure data (safe to import headless in CI); the rendering helpers use Streamlit.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.scoring import Candidate


def candidate_row(c: Candidate, is_new: bool = False) -> dict:
    """One ranked candidate -> a flat, JSON-serializable table row. The leading
    underscore columns are hidden from display and used only for filtering."""
    return {
        "🆕": "🆕" if is_new else "",
        "Symbol": c.symbol,
        "Name": c.name,
        "Rally Score": c.score,
        "Price": c.last_close,
        "Trend": c.closes or [],
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
        "Research": f"https://finviz.com/quote.ashx?t={c.symbol}",
        "_mkt_cap": c.market_cap or 0,
        "_dollar_vol": (c.avg_volume or 0) * (c.last_close or 0),
    }


def display_columns(df: pd.DataFrame) -> list[str]:
    """Visible columns = everything except the underscore-prefixed helpers."""
    return [col for col in df.columns if not col.startswith("_")]


def column_config() -> dict:
    """Rich formatting for the results table — score bars, sparkline, $/%, links."""
    return {
        "🆕": st.column_config.TextColumn("🆕", width="small",
            help="New since the previous list."),
        "Trend": st.column_config.LineChartColumn(
            "Trend (30d)", width="small", help="Recent daily closing price."),
        "Rally Score": st.column_config.ProgressColumn(
            "Rally Score", min_value=0, max_value=100, format="%.0f",
            help="0-100 rally readiness. See 'How the Rally Score is calculated'."),
        "Theme Score*": st.column_config.ProgressColumn(
            "Theme*", min_value=0, max_value=100, format="%.0f",
            help="SPECULATIVE emerging-theme heuristic — NOT a prediction."),
        "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
        "RVOL": st.column_config.NumberColumn("RVOL", format="%.2f", help="Volume vs 20-day avg"),
        "5d %": st.column_config.NumberColumn("5d %", format="%.1f%%"),
        "Float (M)": st.column_config.NumberColumn("Float (M)", format="%.1f"),
        "Mkt Cap ($M)": st.column_config.NumberColumn("Mkt Cap ($M)", format="%.0f"),
        "Short %Float": st.column_config.NumberColumn("Short %Float", format="%.1f%%"),
        "Catalyst": st.column_config.NumberColumn("Catalyst", format="%.0f"),
        "Reddit mentions": st.column_config.NumberColumn("Mentions", format="%d"),
        "Research": st.column_config.LinkColumn("Research", display_text="Finviz ↗"),
    }


def render_results(frame: pd.DataFrame, *, key: str) -> None:
    """Summary metric cards + formatted, sortable table + CSV export + chart."""
    if frame.empty:
        return
    top = frame.iloc[0]
    new_n = int((frame["🆕"] == "🆕").sum()) if "🆕" in frame.columns else 0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Candidates", len(frame))
    c2.metric("🆕 New", new_n)
    c3.metric("Top pick", str(top["Symbol"]), f"{top['Rally Score']:.0f} score")
    c4.metric("Avg rally score", f"{frame['Rally Score'].mean():.0f}")
    c5.metric("With catalyst", int((frame["Catalyst"] > 0).sum()))

    st.dataframe(frame, use_container_width=True, hide_index=True,
                 column_config=column_config())
    st.download_button(
        "⬇️ Download CSV", frame.to_csv(index=False).encode("utf-8"),
        file_name="rally_candidates.csv", mime="text/csv", key=f"dl_{key}")
    st.bar_chart(frame.set_index("Symbol")["Rally Score"])
