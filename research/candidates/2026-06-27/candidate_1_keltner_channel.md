# Candidate: KeltnerChannelTrend

**Date:** 2026-06-27 (Saturday — QuantConnect/Medium blog discovery)
**Source:** Adapted from Keltner Channel breakout literature + BB %B normalization pattern

## Strategy Summary

Keltner Channel %K (normalized position within Keltner Channel) threshold crossover + EMA200 trend filter.

## Entry Conditions (Exactly 2)

1. **Keltner %K threshold:** %K > 0.8 for long, %K < 0.2 for short
   - Keltner Channel: middle = EMA(20), width = ATR(10) × 2.0
   - %K = (Close - KC_lower) / (KC_upper - KC_lower) — normalized 0-1 range
2. **EMA200 trend filter:** Close > EMA200 for long, Close < EMA200 for short

## Exit Conditions

- Exit long when %K < 0.5 (midpoint reversion)
- Exit short when %K > 0.5

## Why This Should Work

- Normalized 0-1 indicator → should work across timeframes like BB %B (4/4 main gate)
- Keltner Channel uses ATR-based width (volatility-adaptive) vs BB's std-based width
- Fixed threshold entry (NOT crossover) → viable on 4h (following %B pattern, not CMO crossover failure pattern)
- ATR-based channel width naturally adapts to volatility regimes without parameter switching
- Exactly 2 AND conditions ✓

## Anti-Pattern Check

- ✅ 2 conditions (not ≥3)
- ✅ Normalized indicator (good for 4h)
- ✅ Fixed threshold, not crossover
- ✅ Not raw price-extreme (uses close, not high/low)
- ✅ Not ETH-hostile indicator family
- ✅ No hidden smoothing gate (ATR(10) < 20 bar limit)

## Predicted Performance

- BTC 1h: Sharpe ~2.5-3.5, ~80-200 trades (comparable to BB %B = 2.90, 194 trades)
- BTC 4h: Sharpe ~1.0-1.5, ~35-50 trades (comparable to BB %B = 1.07, 36 trades)
- ETH 1h: Sharpe ~1.5-2.5, ~80-180 trades (normalized indicator, some ETH robustness)
- ETH 4h: Likely OOS failure (ETH 4h pattern) but main gate pass possible

## Risk Factors

- Keltner Channel may be slightly narrower than BB(20,2) → fewer threshold crossings → lower trade count on 4h
- ATR(10) shorter period may produce choppier channel → more whipsaw on 1h
- If KC %K behaves differently from BB %B (ATR vs std width), normalization advantage may not fully transfer
