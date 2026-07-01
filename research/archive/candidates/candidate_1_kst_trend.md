# Candidate 1: KST Trend (Know Sure Thing)

**Date:** 2026-06-26
**Source:** Quant blog — Martin Pring's KST + community adaptations
**Strategy Type:** Multi-timeframe momentum oscillator, derivative-based

## Rationale

KST (Know Sure Thing) by Martin Pring is a multi-timeframe momentum oscillator that sums 4 different Rate-of-Change (ROC) measurements, each smoothed to its appropriate timescale. It's structurally different from every oscillator tested across 14 loops:

- NOT smoothed like RSI/Wilder (tested, failed)
- NOT sum-based like CMO (tested, 3/4 pass)
- NOT transformation-based like Fisher (tested, 4/4 pass)
- NOT single-period like Stochastic/Williams %R (tested, 4/4 pass)

KST combines multiple timeframe momentum into a single composite — theoretically more robust than single-period oscillators because it captures momentum at short, medium, and long timescales simultaneously.

**Key advantage:** KST is purely derivative-based (ROC = first derivative of price). Follows the proven "derivative > crossover" meta-pattern from Loop 14 where EMASlopeATR (derivative-based) outperformed EMACrossATRFilter (crossover-based).

## Entry Logic (2 conditions)

1. **KST > KST signal line** — KST crosses above its 9-period SMA (bullish); crosses below (bearish)
2. **Close > EMA200** (long) / **Close < EMA200** (short) — trend direction filter

## Exit Logic

KST crosses below signal line (long) / crosses above signal line (short)

## Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| kst_roc1 | 10 | Short-term ROC period |
| kst_roc2 | 15 | Medium-term ROC period |
| kst_roc3 | 20 | Long-term ROC period |
| kst_roc4 | 30 | Very long-term ROC period |
| kst_ma1 | 10 | Smoothing for ROC1 |
| kst_ma2 | 10 | Smoothing for ROC2 |
| kst_ma3 | 10 | Smoothing for ROC3 |
| kst_ma4 | 15 | Smoothing for ROC4 |
| kst_signal | 9 | Signal line SMA period |
| trend_period | 200 | EMA trend filter period |

## Anti-Pattern Compliance

- ✅ 2 AND conditions (KST cross + EMA200 trend)
- ✅ Derivative-based entry (ROC is first derivative)
- ✅ No hidden smoothing gates (signal SMA=9 is standard, well under 20-bar rule)
- ✅ No raw price-extreme (KST is smoothed momentum, not bar extremes)
- ✅ Normalized-ish (KST values cross zero consistently regardless of price level)

## Expected Trade Profile

- 1h: 80-150 trades/year (similar to CMO/Stochastic family oscillators)
- 4h: 25-40 trades/year (dependent on KST period; the multi-timeframe summing may produce more crosses than single-period oscillators)
- Pairs: BTC/USDT, ETH/USDT on 1h and 4h
