# Candidate: Elder Ray Bull/Bear Power Trend

**Date:** 2026-06-28
**Loop:** 36
**Source:** Alexander Elder (classic indicator, novel for this project)

## Strategy Idea

Use Elder Ray Bull Power (High - EMA(13)) as the entry trigger. When Bull Power crosses above zero, buyers are in control — enter long. Short when Bear Power (Low - EMA(13)) is below zero. Filter with EMA(200) for trend direction.

This is a buying/selling pressure indicator that measures raw bar extremes relative to consensus value (EMA). It's NOT an oscillator (no 0-100 normalization), NOT a crossover, and NOT volume-weighted — it measures direct directional pressure.

## Entry Conditions (Exactly 2)
1. **BullPower > 0** (for long) / **BearPower < 0** (for short) — buyers/sellers in control
2. **Close > EMA(200)** — uptrend filter

## Why Novel
- Not tested in 35 prior loops
- Different from ForceIndexTrend (which uses volume × price change) — Elder Ray measures bar extremes, not cumulative force
- Different from oscillators (uses raw High/Low vs EMA, not normalized)
- 2 conditions, no hidden AND gates
- Matches successful template: directional pressure + trend filter

## Anti-Pattern Check
- ✅ Not ≥3 conditions (exactly 2)
- ✅ Not CLV-based
- ✅ Not candle pattern
- ✅ Not adaptive indicator (fixed EMA periods)
- ✅ Not Laguerre/low-lag RSI variant
- ✅ Works on 1h primarily (EMA periods short enough for signal generation)

## Expected Parameters
```python
DEFAULT_PARAMS = {
    "ema_period": 13,       # Elder's standard: 13-bar EMA
    "trend_period": 200,    # Trend filter
    "min_bars": 200,        # Need trend EMA to mature
}
```

## Expected Trade Count
BullPower oscillates around zero naturally (by construction: High - EMA). On 1h, should produce 50-200 trades/year. On 4h, may be trade-scarce (standard 4h limitation).
