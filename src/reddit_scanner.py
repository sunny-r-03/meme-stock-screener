"""Scan Reddit for ticker mentions via PRAW (Reddit's official API).

Reddit blocks the old no-auth JSON endpoint (HTTP 403), so we authenticate with
a free Reddit "script" app. It still costs nothing — you just register an app
once and put the credentials in a .env file. See README for the 3-minute setup.

`momentum` = mentions weighted toward newer / higher-scored posts, so a ticker
that *just* started getting talked about scores higher than steady old chatter.
"""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass

from .ticker_universe import valid_symbols

SUBREDDITS = ["wallstreetbets", "stocks", "pennystocks", "smallstreetbets", "stockmarket"]

CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
BARE = re.compile(r"\b([A-Z]{1,5})\b")


@dataclass
class TickerBuzz:
    symbol: str
    mentions: int
    momentum: float
    posts: int
    sample_titles: list[str]


def _load_env():
    """Minimal .env loader so we don't add a dependency just for this."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _get_reddit():
    """Return an authenticated read-only PRAW client, or None if not configured."""
    _load_env()
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        return None
    try:
        import praw
    except ImportError:
        return None
    try:
        reddit = praw.Reddit(
            client_id=cid,
            client_secret=secret,
            user_agent=os.environ.get("REDDIT_USER_AGENT", "rally-radar/1.0"),
        )
        reddit.read_only = True
        return reddit
    except Exception:
        return None


def _extract(text: str, valid: set[str]) -> set[str]:
    found = set()
    for sym in CASHTAG.findall(text or ""):
        if sym.upper() in valid:
            found.add(sym.upper())
    for sym in BARE.findall(text or ""):
        if sym in valid:
            found.add(sym)
    return found


def scan(limit_per_sub: int = 75, include_rising: bool = True) -> list[TickerBuzz]:
    """Scan configured subreddits and return ranked ticker buzz.

    Returns an empty list (not an error) if Reddit credentials aren't set up,
    so the rest of the app degrades gracefully to watchlist-only.
    """
    reddit = _get_reddit()
    if reddit is None:
        return []

    valid = valid_symbols()
    mentions: dict[str, int] = defaultdict(int)
    momentum: dict[str, float] = defaultdict(float)
    posts: dict[str, int] = defaultdict(int)
    titles: dict[str, list[str]] = defaultdict(list)

    now = time.time()
    listings = ["hot", "new", "rising"] if include_rising else ["hot", "new"]

    for sub_name in SUBREDDITS:
        sub = reddit.subreddit(sub_name)
        for listing in listings:
            try:
                fetcher = {"hot": sub.hot, "new": sub.new, "rising": sub.rising}[listing]
                for post in fetcher(limit=limit_per_sub):
                    blob = f"{post.title or ''} {getattr(post, 'selftext', '') or ''}"
                    syms = _extract(blob, valid)
                    if not syms:
                        continue
                    age_hours = max((now - post.created_utc) / 3600, 0.5)
                    weight = (1.0 / age_hours) * (1 + (post.score or 0) / 500)
                    for s in syms:
                        mentions[s] += 1
                        momentum[s] += weight
                        posts[s] += 1
                        if len(titles[s]) < 3 and post.title:
                            titles[s].append(post.title[:140])
            except Exception:
                continue

    results = [
        TickerBuzz(
            symbol=s,
            mentions=mentions[s],
            momentum=round(momentum[s], 2),
            posts=posts[s],
            sample_titles=titles[s],
        )
        for s in mentions
    ]
    results.sort(key=lambda t: t.momentum, reverse=True)
    return results
