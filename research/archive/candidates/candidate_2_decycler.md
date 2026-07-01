# Candidate: Ehlers Decycler Trend (DecyclerTrend)

**Date:** 2026-06-28
**Source:** 自由搜索 - John F. Ehlers "Cybernetic Analysis for Stocks and Futures" + TradingView Decycler implementation (Mar 2026)
**Status:** Candidate

## Core Idea

Ehlers Decycler crossover with EMA200 trend filter. The Decycler extracts the trend component from price by subtracting a 2-pole Butterworth high-pass filter output (the "cycler") from the original price. What remains is everything longer than the cutoff period — with near-zero phase lag. This is frequency-domain filtering (DSP), fundamentally different from all time-domain moving averages tested across 34 loops.

## Signal Logic

- **Entry:** Decycler crosses above its trigger line (Decycler lagged 1 bar) AND close > EMA200 → Long
- **Exit:** Decycler crosses below trigger line → Flat
- **Conditions:** 2 (Decycler crossover + trend filter)

## Why This Should Work

1. The Decycler's zero-phase-lag property means it responds to trend changes in near-real-time — no MA-type smoothing delay
2. The 2-pole Butterworth high-pass filter is mathematically optimal for separating trend from cycle — not a heuristic
3. This is the first DSP-based indicator tested in 34 loops — completely unexplored indicator family
4. Near-zero lag means 4h signal density should be higher than any time-domain crossover (including ALMA)
5. 2 conditions total — respects the proven template

## Anti-Pattern Check

- ✅ NOT signal-sparse (zero-lag crossover generates frequent signals)
- ✅ NOT 3+ conditions (2 conditions: decycler crossover + trend filter)
- ✅ NOT mean reversion (trend extraction is inherently trend-following)
- ✅ NOT efficiency-ratio smoothed (DSP filtering, not adaptive smoothing)
- ✅ NOT candle-pattern based (mechanical crossover)
- ✅ NOT triple-smoothing (single Butterworth filter, one stage)

## Risks

- Butterworth filter requires a cutoff period parameter — too short and it passes cycles (noise), too long and it lags
- ETH 1h: DSP filtering may expose the same microstructure noise as other zero-lag indicators
- 4h: Fewer bars (2190/year) means fewer filter updates — but zero-lag property should preserve trade count
- Mathematical complexity: correct implementation requires understanding of Butterworth filter coefficients

## Parameters

```python
DEFAULT_PARAMS = {
    "cutoff_period": 20,  # Decycler cutoff period (bars) — removes cycles shorter than this
    "trend_period": 200,  # EMA trend filter period
    "min_bars": 150       # Minimum bars for warmup (DSP filters need filter initialization)
}
```

## Decycler Calculation

The Decycler is computed as:
1. Compute 2-pole Butterworth high-pass filter coefficients for given cutoff_period
2. Apply high-pass filter to price → "cycler" (cyclic component)
3. Decycler = price - cycler (trend component with cycles removed)
4. Trigger = Decycler shifted by 1 bar (Ehlers' standard approach)

## Expected Results

- BTC 1h: Sharpe 1.3-1.9, 120-200 trades (zero-lag should match/exceed ALMA)
- ETH 1h: Sharpe 0.5-1.0 (DSP may handle ETH noise better than time-domain), 120-200 trades
- BTC 4h: Sharpe 1.0-1.6, 35-60 trades (zero-lag crossover on 4h)
- ETH 4h: Sharpe 0.3-0.7 (ETH 4h hostile regime), 30-50 trades
