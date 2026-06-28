"""Social signal via ApeWisdom's free public API — no keys, no signup.

ApeWisdom aggregates ticker mentions across Reddit (WSB, r/stocks, etc.) and,
crucially, also reports mentions 24h ago — so we can measure mention *growth*,
which the research found is the leading attention signal (a crowd *forming*),
not just raw chatter.

Endpoint (no auth): https://apewisdom.io/api/v1.0/filter/{filter}/page/{n}
Returns: {"results": [{"ticker","name","mentions","mentions_24h_ago","rank",
                       "upvotes", ...}, ...], "pages": N, ...}

We reuse the TickerBuzz dataclass so the rest of the app is unchanged.
"""
from __future__ import annotations

import requests

from .reddit_scanner import TickerBuzz

API = "https://apewisdom.io/api/v1.0/filter/{flt}/page/{page}"
HEADERS = {"User-Agent": "rally-radar/1.0"}


def scan(flt: str = "all-stocks", pages: int = 2) -> list[TickerBuzz]:
    """Return ranked ticker buzz from ApeWisdom.

    `momentum` rewards both volume of mentions AND acceleration (growth vs 24h
    ago), so a ticker whose chatter is *spiking* ranks above one with flat
    chatter. Returns [] on any network error so the app degrades gracefully.
    """
    out: list[TickerBuzz] = []
    for page in range(1, pages + 1):
        try:
            resp = requests.get(API.format(flt=flt, page=page), headers=HEADERS, timeout=20)
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except Exception:
            break
        if not results:
            break
        for r in results:
            try:
                sym = str(r["ticker"]).upper()
                mentions = int(r.get("mentions") or 0)
                prior = int(r.get("mentions_24h_ago") or 0)
                growth = mentions - prior
                # Momentum = current chatter + a bonus for acceleration.
                momentum = mentions + 2 * max(growth, 0)
                pct = f"{(growth / prior * 100):+.0f}% 24h" if prior else "new"
                note = (f"ApeWisdom rank #{r.get('rank','?')} on {flt}: "
                        f"{mentions} mentions ({pct}), {r.get('upvotes', 0)} upvotes")
                out.append(TickerBuzz(
                    symbol=sym,
                    mentions=mentions,
                    momentum=round(float(momentum), 2),
                    posts=mentions,
                    sample_titles=[note],
                ))
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda t: t.momentum, reverse=True)
    return out
