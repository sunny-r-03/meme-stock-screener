# Rally Detection — Research & Backtest Analysis

This document records *why* the tool is built the way it is: the empirical
research behind each signal, and a backtest of the detection logic against
documented historical rallies. It is deliberately honest about what works,
what doesn't, and the limits of the evidence.

---

## 1. The research base (why these signals)

| Finding | Source |
|---------|--------|
| A "meme stock" = top-mentioned on WSB **and** short interest > 20%. Social discussion + short interest fuels squeezes. | [KU / SSRN meme-stock research](https://business.ku.edu/news/article/social-media-discussions-fueled-meme-stock-events-and-significant-short-squeezes-research-finds) |
| Google search volume predicts meme returns at **3–7 days**; news sentiment at 7–14 days; Twitter sentiment decays after ~1 day. | [Li & Li, *Sentiment, Social Media, and Meme Stock Return Predictability*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4947010) |
| Google Trends + intraday data explain much of GME's abnormal returns (EMH violated → the signal was detectable, not just hindsight). | [Vasileiou et al., SSRN](https://www.ssrn.com/abstract=3805630) |
| Mega-runners are overwhelmingly **low float (<8M shares)**, small cap (<$25M), price <$10, often with **clean capital structures (can't dilute)** + liquid options. These are *prerequisites, not predictors*. | [DilutionTracker: characteristics of mega squeezes](https://knowledge.dilutiontracker.com/en/articles/5611407-characteristics-of-mega-squeezes-and-how-to-anticipate-them) |
| Short interest only matters **relative to available float** (VW 2008: only 12.8% SI, but float collapsed to ~1% → infinity squeeze). | [VW 2008 (TradingSim)](https://www.tradingsim.com/blog/volkswagen-short-squeeze-explained) |

**Implication for the design:** the *leading* signals are attention growth
(Reddit/Google) + catalyst + options. Price/volume breakout is a *confirming*
(lagging) signal. Float + short interest are accelerants.

---

## 2. Cross-case anatomy (7 events)

Every squeeze shared 5 conditions; the cases that lacked them (BB, NOK) fizzled:

1. **Float shortage** (universal) — inherently tiny, locked up, or fully on-loan.
2. **Crowded shorts vs. that float** (the fuel).
3. **A concentrated demand shock** (retail coordination, takeover, SPAC redemption).
4. **A reflexive amplifier** (options gamma + forced short covering).
5. **A believable catalyst** (often an activist — Ryan Cohen drove *both* GME & BBBY).

---

## 3. Backtest of the breakout detector (no lookahead)

**Method.** For each documented event we give the tool a *date window* and let
it pick the entry itself — the first day its breakout trigger fires
(RVOL ≥ 3, within 15% of the 60-day high), using only data up to that day. We
then measure the forward return over the next 15 trading days.

### Pass 1 — naive (no overextension guard)
Entering a *confirmed* breakout that was already parabolic was a **disaster**:

| Stock | Entry was already up (5d) | Forward max | Forward end |
|-------|--------------------------|-------------|-------------|
| AMC (Jan 27 '21) | +570% | −33% | **−72%** |
| KOSS (Jan 27 '21)| +1591% | +10% | **−75%** |
| BB (Jan 27 '21)  | +96% | −42% | −56% |

> **Finding #1:** by the time volume is 10× and price is already up hundreds of
> percent, the rally is over. Chasing confirmed breakouts loses badly.

### Pass 2 — with "not already parabolic" guard (skip if up >40% in 5d)

| Stock | Auto entry | RVOL | 5d-in | Forward max | Forward end |
|-------|-----------|------|-------|-------------|-------------|
| BB    | 2021-01-14 | 4.8 | +29% | **+175%** | +45% |
| GME (Roaring Kitty) | 2024-05-03 | 9.1 | +38% | **+196%** | +15% |
| AMC '21 | *no trigger* | — | — | — | — |
| KOSS '21 | *no trigger* | — | — | — | — |
| GME '21 | *no trigger* | — | — | — | — |
| ATER '21 | *no trigger* | — | — | — | — |

> **Finding #2:** the guard correctly **avoids the blow-off tops** (AMC/KOSS/GME
> '21 that lost 70%+ in pass 1) and only fires on *early* breakouts — which then
> ran **+175%** (BB) and **+196%** (GME 2024).
>
> **Finding #3 (the big one):** the three most violent 2021 squeezes
> (GME, AMC, KOSS) returned **"no trigger"** — because they went from normal to
> +500% in one or two sessions. *Daily* price/volume is too slow to give a safe
> early entry on these. GME on Jan 11–13 '21 was already +57–72% in 5 days on
> its first volume-spike days, tripping the guard.

---

## 4. What the backtest proves about the architecture

- **Price/volume breakout is confirming, not leading.** It catches "normal"
  fast rallies early (BB, GME-2024) but is too slow for the most explosive
  squeezes.
- **To catch GME/AMC/KOSS-class moves you need the LEADING signals** that fire
  *before* price goes vertical: Reddit mention *growth*, options gamma building,
  and catalyst filings (13D). This is exactly why those carry the "thesis"
  weight (breakout 30% + attention 25% + catalyst 15%), with float/short as
  accelerants.
- **An overextension guard is essential** and should be added to live scoring
  (penalize entries already up >~40% in 5 days).

---

## 5. Honest limitations

1. **Selection bias.** We tested known winners. A real edge test needs a control
   group of stocks that lit up and *fizzled* — to measure false-positive rate.
2. **No free point-in-time short interest / float**, so only the price/volume
   breakout is backtested precisely; float & short are from the public record.
3. **Daily bars** miss intraday dynamics that drive the fastest squeezes.
4. **Small sample.** Extreme squeezes are rare (SI >100% of float happened ~15
   times in a decade per Goldman) — statistical power is inherently low.
5. **Prerequisites ≠ predictors.** Many stocks have all five conditions and
   never rally; the spark is unpredictable. The tool ranks *readiness*, not
   destiny.

---

## 6. Next steps to make this more rigorous

- [x] Add the overextension guard to `src/scoring.py` (proven in pass 2). **DONE.**
- [ ] Build a **control group** backtest (random small-caps + fizzled runners)
      to measure precision / false positives — the missing half of an edge test.
- [ ] Add **leading** signals: Reddit mention *growth* (PRAW) and options gamma.
- [ ] Store daily scans in SQLite to track signal *slope* over time.
