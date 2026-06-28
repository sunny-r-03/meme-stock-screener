# 🚀 Small-Cap Rally Radar

A **long/buy** screener: finds small-cap stocks that look ready to **rally (go
up)**, so you can research buying them. It ranks rally *readiness* from
breakout momentum + attention + thin float + short-interest fuel.

> **We go long — we never short.** Short interest is used only as an
> *accelerant*: trapped short-sellers are forced to BUY, which fuels an up-move
> (a short squeeze IS a rally). It is a buy signal here, not a sell signal.

> ⚠️ **Educational tool, not financial advice.** It surfaces *candidates* for
> you to research. It does **not** predict that any stock will go up. Most
> candidates will not rally. Small-cap stocks are extremely risky.

## How it works

1. **Candidate tickers** — two modes:
   - **Whole market** (`src/market_scanner.py`): bulk-downloads recent
     price+volume for all ~12,000 US tickers (~3-5 min) and keeps only the ones
     breaking out (high relative volume + rising). This finds *all* rallies, no
     hand-picking.
   - **Watchlist**: just the tickers you type in.
   Optionally fold in Reddit buzz (once PRAW is set up).
2. **Validate tickers** against the real NASDAQ/NYSE symbol list so words like
   "CEO" or "YOLO" aren't mistaken for stocks.
3. **Breakout signal** (`src/breakout.py`): relative volume, 5-day return, and
   proximity to recent highs — confirms a rally is actually igniting *now*.
4. **Fundamentals** (`src/fundamentals.py`): float size, market cap, short %,
   price — free via `yfinance`.
5. **Catalyst** (`src/edgar.py`): scans free SEC EDGAR filings for the "reason
   to buy" — activist stakes (SC 13D, the Ryan Cohen signal), recent material
   events (8-K). It *subtracts* for dilution filings (S-1/S-3/424B), since a
   company that can print new shares can cap a squeeze.
6. **Rally score** (`src/scoring.py`): weighted blend — breakout + attention +
   catalyst as the thesis; small float + short interest as accelerants.
7. **Display** a ranked dashboard in your browser.

> SEC asks API users to send a descriptive User-Agent. Optionally set
> `SEC_USER_AGENT="yourapp/1.0 (you@email.com)"` in your `.env`.

## Setup

```bash
cd meme-stock-screener
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Your browser opens at http://localhost:8501. Set filters in the sidebar and
click **Run scan**. The first run downloads the ticker list (~1 minute).

## Turn on the Reddit signal (free, optional but key)

Reddit/WSB attention was the catalyst behind GameStop, so it's worth enabling.
Reddit blocks anonymous access, so you need a free "script" app:

1. Go to https://www.reddit.com/prefs/apps and click **create another app...**
2. Choose type **script**; redirect uri `http://localhost:8080` (unused).
3. Copy `.env.example` to `.env` and paste in the **client ID** (under the app
   name) and **secret**.
4. In the dashboard, tick **"Scan Reddit for buzz"** and scan.

Without `.env`, the Reddit signal is simply skipped (the app still works on the
watchlist + breakout + fundamentals).

## Tuning

- **Scoring weights** live in `src/scoring.py` (`WEIGHTS`). Care more about
  short squeezes? Bump `short`.
- **Subreddits** are in `src/reddit_scanner.py` (`SUBREDDITS`).
- **Market-cap sweet spot** is in `src/scoring.py` (`_smallcap_score`).

## Limits & honest caveats

- yfinance short-interest data lags (reported twice a month by FINRA).
- Reddit's public JSON is rate-limited; the scanner sleeps between calls.
- This finds *correlation with hype*, not *causation of price moves*. Most
  buzzed small caps do **not** become GameStop.

## Ideas to extend

- Add a price-history sparkline + unusual-volume flag.
- Cache scans and chart momentum **change** day-over-day (the real signal).
- Add options data (gamma squeeze potential).
- Schedule a daily run and email the top 10 (Streamlit + cron).
