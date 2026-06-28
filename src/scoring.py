"""Combine signals into a single RALLY-readiness score (a long/buy radar).

We are hunting stocks likely to rally UP so they can be bought. We are NOT
shorting anything. Short interest is included only as an *accelerant* — trapped
short-sellers are forced to BUY, which fuels an up-move (a squeeze IS a rally).

Core rally drivers (the thesis):
  - attention growth  -> a crowd is forming and buying
  - breakout momentum -> the rally is actually igniting (volume + price)
  - catalyst          -> people have a concrete reason to buy

Accelerants (make a rally bigger when present, but aren't the thesis):
  - small float       -> little buying moves price a lot
  - short interest    -> forced covering adds buy pressure
  - liquidity sanity  -> tradeable, but not so liquid it can't move

This ranks rally *readiness*. It does not predict prices. Most candidates will
not rally — the spark is unpredictable. Treat it as a research radar.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .breakout import Breakout, score as breakout_score
from .fundamentals import Fundamentals
from .reddit_scanner import TickerBuzz
from .theme import assess as assess_theme

WEIGHTS = {
    "breakout": 0.30,   # rally igniting now (volume + price)
    "social": 0.25,     # attention / crowd forming
    "catalyst": 0.15,   # reason to buy (filled by EDGAR module later)
    "smallfloat": 0.15, # accelerant: thin float amplifies buying
    "short": 0.10,      # accelerant: trapped shorts must buy
    "liquidity": 0.05,  # tradeable sanity check
}


@dataclass
class Candidate:
    symbol: str
    name: str | None
    score: float
    last_close: float | None
    market_cap: float | None
    float_shares: float | None
    short_pct_float: float | None
    rvol: float | None
    ret_5d: float | None
    momentum: float
    mentions: int
    catalyst_score: float
    catalyst_notes: list[str]
    sector: str | None
    sample_titles: list[str]
    avg_volume: float | None = None       # for the 'well-known' liquidity proxy
    theme_tags: list[str] = field(default_factory=list)  # speculative, see theme.py
    theme_score: float = 0.0              # 0-100, SPECULATIVE — not a prediction


def _social_score(buzz: TickerBuzz | None, max_momentum: float) -> float:
    if buzz is None or max_momentum <= 0:
        return 0.0
    return min(buzz.momentum / max_momentum, 1.0) * 100


def _short_score(f: Fundamentals) -> float:
    # Accelerant: 20%+ of float short is high. (We BUY these, never short them.)
    if f.short_pct_float is None:
        return 0.0
    return min(f.short_pct_float / 20.0, 1.0) * 100


def _smallfloat_score(f: Fundamentals) -> float:
    # Thin float amplifies any buying. <8M shares = max (per mega-runner data),
    # decaying to 0 by ~150M shares. Falls back to market cap if float missing.
    fl = f.float_shares
    if fl and fl > 0:
        if fl <= 8_000_000:
            return 100.0
        if fl >= 150_000_000:
            return 0.0
        return max(0.0, 100 * (1 - (fl - 8_000_000) / (150_000_000 - 8_000_000)))
    # Fallback: market-cap proxy.
    mc = f.market_cap
    if not mc or mc <= 0:
        return 0.0
    if mc <= 50_000_000:
        return 100.0
    if mc >= 2_000_000_000:
        return 0.0
    return max(0.0, 100 * (1 - (mc - 50_000_000) / (2_000_000_000 - 50_000_000)))


def _liquidity_score(f: Fundamentals) -> float:
    # Need *some* volume to enter/exit, but mega-liquid names barely move.
    if not f.avg_volume:
        return 0.0
    if f.avg_volume < 50_000:
        return 20.0
    if f.avg_volume > 50_000_000:
        return 40.0
    return 100.0


def build_candidate(
    f: Fundamentals,
    b: Breakout,
    buzz: TickerBuzz | None,
    max_momentum: float,
    catalyst: float = 0.0,
    catalyst_notes: list[str] | None = None,
) -> Candidate:
    """Combine all signals for one ticker. `catalyst` is 0-100 (from EDGAR)."""
    score = (
        WEIGHTS["breakout"] * breakout_score(b)
        + WEIGHTS["social"] * _social_score(buzz, max_momentum)
        + WEIGHTS["catalyst"] * catalyst
        + WEIGHTS["smallfloat"] * _smallfloat_score(f)
        + WEIGHTS["short"] * _short_score(f)
        + WEIGHTS["liquidity"] * _liquidity_score(f)
    )
    # Overextension guard (validated in backtest pass 2): a stock already up huge
    # over 5 days is a CHASE, not an entry — buying confirmed parabolic breakouts
    # lost 70%+ historically. Dampen the score the further past +40% it is.
    ret5 = b.ret_5d if b.ok else None
    if ret5 and ret5 > 40:
        score *= max(0.4, 1 - (ret5 - 40) / 160)  # ~half by +120%, floor 0.4x

    # Speculative Emerging-Theme heuristic (kept SEPARATE from the rally score so
    # it stays clearly labelled — it is NOT a prediction). See src/theme.py.
    momentum_norm = (buzz.momentum / max_momentum) if (buzz and max_momentum > 0) else 0.0
    theme = assess_theme(f, momentum_norm)

    return Candidate(
        symbol=f.symbol,
        name=f.name,
        score=round(score, 1),
        last_close=b.last_close if b.ok else f.price,
        market_cap=f.market_cap,
        float_shares=f.float_shares,
        short_pct_float=f.short_pct_float,
        rvol=b.rvol if b.ok else None,
        ret_5d=b.ret_5d if b.ok else None,
        momentum=buzz.momentum if buzz else 0.0,
        mentions=buzz.mentions if buzz else 0,
        catalyst_score=round(catalyst, 1),
        catalyst_notes=catalyst_notes or [],
        sector=f.sector,
        sample_titles=buzz.sample_titles if buzz else [],
        avg_volume=f.avg_volume,
        theme_tags=theme.tags,
        theme_score=theme.score,
    )
