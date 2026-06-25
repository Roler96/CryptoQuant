# Candidate 1: KamaTrend — Adaptive Acceleration Trend Following

**Date:** 2026-06-25
**Source:** arXiv SSR analysis + QuantifiedStrategies.com
**Type:** Trend-following, acceleration-based

## Rationale

Kaufman's Adaptive Moving Average (KAMA) uses an Efficiency Ratio to dynamically adjust its smoothing constant. In trending markets (high ER), KAMA follows price closely (acts like a fast EMA). In choppy/noisy markets (low ER), KAMA lags more (acts like a slow EMA). This self-adaptation eliminates the need for parameter switching across volatility regimes.

**Why this could work:**
- PSAR (acceleration-based) achieved 4/4 gate pass. KAMA uses a *different* adaptation mechanism (efficiency ratio vs acceleration factor) — it responds to trend smoothness, not price direction persistence.
- A 2025 SSRN paper specifically analyzed KAMA on Bitcoin with bootstrap validation and Bayesian optimization.
- KAMA is less whipsaw-prone than standard EMAs while maintaining trend sensitivity.
- Only 2 AND conditions (KAMA crossover + trend filter) — obeys the 2-condition rule.

## Entry Conditions (exactly 2 AND conditions)
1. KAMA_fast crosses ABOVE KAMA_slow (bullish crossover)
2. Close > EMA(200) (trend direction filter)

## Exit Conditions
- KAMA_fast crosses BELOW KAMA_slow (reverse crossover)

## Parameters
- `er_period`: 10 (efficiency ratio lookback)
- `fast_ema`: 2 (fastest EMA for SC computation)
- `slow_ema_fast`: 30 (slow EMA for fast KAMA)
- `slow_ema_slow`: 50 (slow EMA for slow KAMA)
- `trend_period`: 200 (EMA trend filter)
- `min_bars`: 200 (conservative — KAMA needs ER computation bars)

## Expected Trade Count
- 1h: 80-200 trades/year (adaptive crossover generates frequent signals)
- 4h: 30-60 trades/year (adaptive mechanism may generate enough on 4h unlike fixed-lookback)

## Anti-Patterns Avoided
- ✓ 2 conditions (not ≥3)
- ✓ Acceleration-based (not lag-based like standard MA crossover)
- ✓ No ADX, no CLV, no candle patterns, no Ichimoku
- ✓ Not mean reversion without trend filter
- ✓ Not volume percentile gate

## Transferable Hypothesis
If KAMA's efficiency-ratio adaptation produces cleaner signals than fixed-period MAs, this strategy should outperform EMACrossATRFilter (Loop 1) on a per-signal basis, with similar or lower trade count.
