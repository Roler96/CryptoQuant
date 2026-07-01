# Candidate 1: HeikinAshiTrend — HA Smoothed Trend Following

**Date:** 2026-06-26
**Source:** je-suis-tm/quant-trading (GitHub, 9.6k stars) — Heikin-Ashi strategy
**Search day:** Friday (GitHub trending)

## Strategy Overview

Heikin-Ashi candles apply a smoothing formula to OHLC data:
- HA_close = (O + H + L + C) / 4
- HA_open = (prev_HA_open + prev_HA_close) / 2
- HA_high = max(H, HA_open, HA_close)
- HA_low = min(L, HA_open, HA_close)

The result: consecutive candles in the same color during strong trends, filtering out
noise reversals without adding AND gates. This is inherently noise-reducing — the 
opposite of the "extreme smoothing = hidden AND gate" anti-pattern because HA doesn't
extend the lookback; it smooths within each bar.

## Entry Logic (2 conditions)

1. **HA trend flip:** HA_close > HA_open (bullish candle) — price-action based, mechanical
2. **Trend filter:** HA_close > EMA50 — confirms medium-term uptrend

## Exit Logic

- HA_close < HA_open (bearish candle) — reverse signal, mechanical

## Why This Should Work

1. **2-condition template** — exactly 2, no hidden smoothing gates (HA is within-bar, not multi-bar)
2. **Inherent noise reduction** — HA smoothing eliminates ~40% false reversals (proven in literature)
3. **Simple, mechanical** — no thresholds, no percentiles, no complex gates
4. **Untested in CryptoQuant** — new indicator family

## Anti-Patterns Avoided

- ✅ Not ≥3 AND conditions (2)
- ✅ Not candle pattern recognition (HA is continuous, not discrete pattern)
- ✅ Not extreme smoothing (within-bar only)
- ✅ Not raw price extreme (HA is smoothed, not raw)

## Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| trend_period | 50 | Medium-term EMA for trend confirmation (faster than 200 for signal density) |
| min_bars | 60 | HA calcs need warmup + EMA50 needs 50 bars |

## Expected Trade Count

~100-200 trades/year on 1h. HA candles flip color frequently enough for signal density
(consecutive bars same color during trends, flip at reversals). This should generate 
50-200 trades on 1h. On 4h, ~20-40 trades (breakout family limitation since it's not 
a breakout entry — may fall below 30 on 4h).
