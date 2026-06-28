"""Speculative 'Emerging-Theme' heuristic — NOT a predictor.

WARNING / honest caveat: this CANNOT predict which products or companies will
become popular. Foreseeing something like the AI boom from financial data alone
is not a screening problem — the eventual winners looked expensive and
speculative on every standard metric until they didn't. This module only
surfaces companies whose *profile rhymes* with early-stage secular-trend
winners, using free yfinance fields. Expect MANY false positives. Treat a high
theme score as a research prompt, never a forecast.

The score blends four cheap, free signals:
  - Theme tag      -> does the business touch a fast-moving theme? (keyword scan)
  - Revenue growth -> is the top line accelerating? (a young trend grows fast)
  - Gross margin   -> is the product scalable? (software-like economics)
  - Attention      -> is a crowd already forming? (reused social momentum)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .fundamentals import Fundamentals

# Hot themes -> lowercase keywords scanned in the business summary + industry.
# Deliberately broad; precision is impossible here, so we favour recall.
THEMES: dict[str, list[str]] = {
    "AI": [
        "artificial intelligence", "machine learning", "deep learning",
        "neural network", "large language", "generative ai", "inference",
        " ai ", "ai-", "data center", "accelerator",
    ],
    "Semiconductors": [
        "semiconductor", "chip", "wafer", "foundry", "lithography",
        "integrated circuit", "gpu",
    ],
    "Robotics/Automation": [
        "robot", "robotic", "automation", "autonomous", "drone", "lidar",
    ],
    "Quantum": ["quantum"],
    "Nuclear/Fusion": [
        "nuclear", "uranium", "fusion", "small modular reactor", " smr ",
    ],
    "Clean Energy/EV": [
        "solar", "battery", "hydrogen", "renewable", "lithium",
        "electric vehicle", "charging", "photovoltaic",
    ],
    "Biotech/Genomics": [
        "gene", "genomic", "mrna", "crispr", "oncology", "clinical",
        "therapeutic", "biotech", "immunotherapy",
    ],
    "Space": ["satellite", "spacecraft", "launch vehicle", "orbital", "aerospace"],
    "Cybersecurity": ["cybersecurity", "cyber security", "endpoint", "zero trust"],
    "Defense": ["defense", "missile", "military", "warfare", "munition"],
    "Crypto/Blockchain": [
        "bitcoin", "crypto", "blockchain", "digital asset", "ethereum",
    ],
}


@dataclass
class Theme:
    tags: list[str] = field(default_factory=list)
    score: float = 0.0  # 0-100, SPECULATIVE


def detect_themes(summary: str | None, industry: str | None) -> list[str]:
    """Tag which hot themes a company's description touches (keyword match)."""
    text = f" {(summary or '')} {(industry or '')} ".lower()
    return [name for name, kws in THEMES.items() if any(kw in text for kw in kws)]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def assess(f: Fundamentals, momentum_norm: float = 0.0) -> Theme:
    """Build the speculative Emerging-Theme score for one company.

    `momentum_norm` is the company's social momentum normalised to 0-1 (its
    momentum / the max momentum seen this scan), reused from the social signal.
    """
    tags = detect_themes(f.summary, f.industry)

    # A real theme tag is the gate: no theme touched -> heavily damped score,
    # since the whole point is *emerging-trend* exposure, not generic growth.
    theme_factor = 1.0 if tags else 0.35

    growth = _clamp01((f.revenue_growth or 0.0) / 50.0)   # +50% YoY = max
    margin = _clamp01((f.gross_margins or 0.0) / 70.0)    # 70% gross = max
    attention = _clamp01(momentum_norm)

    base = 0.45 * growth + 0.30 * margin + 0.25 * attention
    return Theme(tags=tags, score=round(100 * theme_factor * base, 1))
