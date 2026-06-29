# Candidate 1: Linear Regression Slope Trend

**Date:** 2026-06-29
**Source:** Sunday free search — statistical trend measurement domain
**Status:** Candidate

## Concept

Use the slope of a linear regression line over N bars as a trend direction signal. Unlike price-action breakouts (InsideBar, Donchian) or smoothed oscillators (Stochastic, RSI), linear regression slope directly measures statistical trend strength without lag-producing smoothing.

## Entry Signal (2 conditions)

1. **Condition 1 — Regression slope crosses above threshold:**
   - Compute LR slope over `lr_period` bars (e.g., 20)
   - Long when slope > `slope_threshold` (e.g., 0.0 = any positive slope)
   - Short when slope < -`slope_threshold`

2. **Condition 2 — Trend direction filter:**
   - Long only when close > EMA(`trend_period`)
   - Short only when close < EMA(`trend_period`)

## Exit

- Exit long when slope crosses below zero (reverse signal)
- Exit short when slope crosses above zero
- Also exit if price crosses EMA(trend_period) against position direction

## Why This Is Different

All 29 previously tested strategies use either:
- Price-action breakouts (channels, BB, inside bars, PSAR) — 11 strategies
- Smoothed oscillator crossovers (Stochastic, RSI, MACD, Force Index, Aroon, KAMA) — 10 strategies
- Moving average crossovers (EMA, adaptive EMA) — 4 strategies
- Volume-based (CLV, volume spike, candle body) — 4 strategies (all failed)

**Linear regression slope is in NONE of these categories.** It measures statistical directionality using least-squares fit, not price levels, smoothed momentum, or volume. This is a genuinely unexplored signal domain.

## Expected Characteristics

- Signal count: 50–150 trades/year (slope zero-crosses are frequent enough on 1h)
- Commission sensitivity: Low (slope-based signals persist, not micro-oscillations)
- 4h potential: Moderate (2190 bars/year sufficient for 20-bar regression)
- ETH vulnerability: Unknown — first statistical indicator in the suite

## Parameter Space

| Parameter | Default | Range |
|-----------|---------|-------|
| `lr_period` | 20 | 10–50 |
| `slope_threshold` | 0.0 | -0.01 to 0.01 |
| `trend_period` | 200 | 100–300 |
| `min_bars` | 20 | — |

## Anti-Pattern Check

- [x] ≤2 AND conditions (slope threshold + trend filter)
- [x] No ADX, no Ichimoku, no CLV, no candle patterns
- [x] Not mean-reversion (trend filter ensures trend-following direction)
- [x] No hysteresis, no regime switching
- [x] Entry trigger not gated by volume percentile
- [x] min_bars ≤ 300 (set to 20)
