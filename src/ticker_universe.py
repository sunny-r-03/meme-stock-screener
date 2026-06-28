"""Load the real list of US-listed tickers so we can validate Reddit mentions.

Without this, words like "CEO", "USA", "YOLO", "FUD" get mistaken for stock
tickers. We download the official symbol lists from nasdaqtrader.com once and
cache them locally.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache

import pandas as pd
import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CACHE_FILE = os.path.join(CACHE_DIR, "tickers.csv")

# Common words that look like tickers but almost never mean the stock.
# These ARE real tickers but get spammed as English words on Reddit.
BLOCKLIST = {
    "A", "I", "U", "DD", "CEO", "USA", "USD", "IMO", "ALL", "FOR", "ARE",
    "GO", "NOW", "NEW", "ON", "AT", "BE", "BY", "OR", "SO", "IT", "AN",
    "AM", "PM", "EV", "AI", "IPO", "ATH", "WSB", "FD", "FDA", "SEC", "CFO",
    "YOLO", "FUD", "HODL", "RH", "ER", "EPS", "GDP", "ETF", "IRA", "ROI",
    "TLDR", "EOD", "EOW", "OTM", "ITM", "PT", "TA", "PR", "OG", "GG", "WTF",
    "LOL", "LMAO", "OMG", "TOS", "RIP", "MOON", "PUMP", "BUY", "SELL", "HOLD",
}

NASDAQ_URLS = [
    # symbol | name | ... (pipe-delimited)
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
]


def _download_universe() -> pd.DataFrame:
    frames = []
    headers = {"User-Agent": "meme-stock-screener/1.0"}
    for url in NASDAQ_URLS:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), sep="|")
        # Column names differ slightly between the two files; normalize.
        symbol_col = "Symbol" if "Symbol" in df.columns else "ACT Symbol"
        name_col = "Security Name"
        df = df[[symbol_col, name_col]].rename(
            columns={symbol_col: "symbol", name_col: "name"}
        )
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    # The last row of these files is a footer like "File Creation Time..."
    out = out[out["symbol"].notna()]
    out = out[~out["symbol"].astype(str).str.contains("File Creation", na=False)]
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out = out[out["symbol"].str.match(r"^[A-Z]{1,5}$")]
    return out.drop_duplicates(subset="symbol").reset_index(drop=True)


@lru_cache(maxsize=1)
def load_universe(refresh: bool = False) -> pd.DataFrame:
    """Return DataFrame[symbol, name] of valid US tickers, cached on disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(CACHE_FILE) and not refresh:
        return pd.read_csv(CACHE_FILE)
    df = _download_universe()
    df.to_csv(CACHE_FILE, index=False)
    return df


@lru_cache(maxsize=1)
def valid_symbols() -> set[str]:
    """Set of symbols we'll accept as real tickers, minus the blocklist."""
    return set(load_universe()["symbol"]) - BLOCKLIST
