# Candidate: RSIExpansionTrend

**Date:** 2026-06-28
**Loop:** 30
**Status:** DISCOVER

## Strategy Overview

Standalone RSI(14) midline crossover as primary entry trigger, paired with ATR expansion confirmation.

## Signal Logic

1. **Entry (long):** RSI(14) crosses above 50 AND current bar range > 1.5 × ATR(14)
2. **Entry (short):** RSI(14) crosses below 50 AND current bar range > 1.5 × ATR(14)
3. **Exit:** RSI crosses back across 50 (reverse signal)

## Why This Is Novel

- RSI has been used as a **confirmation filter** (ChannelBreakoutRSI, RSI > 50 as gate) and as a **composite component** (Connors RSI = RSI + Streak RSI + PercentRank), but NEVER as the **primary entry trigger** in a standalone strategy.
- Pairing RSI crossover with ATR expansion is a new combination — all previous ATR-expansion strategies used breakout-based entries (channel, inside-bar, Donchian, BB %B), not oscillator crossovers.
- ATR(14) expansion at 1.5× is the most-proven confirmation filter across 28 loops (6/7 perfect 4/4 sweeps).

## Expected Properties

- **Trade count:** 80-200 on 1h, 30-60 on 4h (RSI crosses midline frequently; ATR filter removes ~60% noise)
- **Win rate:** 40-50% (typical for oscillator-based trend following)
- **ETH risk:** RSI single-EMA smoothing means ≤1 smoothing layer → should avoid the ETH smoothing-depth penalty. However, all oscillator-family strategies show ETH OOS fragility.
- **BTC expected Sharpe:** 1.0-2.5 on 1h (aligned with CCI, Stochastic, Williams %R ranges)

## Parameters

```python
DEFAULT_PARAMS = {
    "rsi_period": 14,
    "atr_period": 14,
    "expansion_mult": 1.5,
    "rsi_long_entry": 50,
    "rsi_short_entry": 50,
    "min_bars": 100,
}
```

## Anti-Pattern Check

- ✅ 2 conditions (RSI crossover + ATR expansion)
- ✅ RSI midline crossover is frequent (not signal-sparse like VWAP, HA, TMF)
- ✅ ATR expansion proven universal confirmation filter
- ✅ No hidden smoothing gates (RSI(14) = ~27-bar effective, within 20-bar bound)
- ⚠️ Single oscillator on ETH — expect OOS degradation per established ETH pattern
