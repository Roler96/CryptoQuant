# Candidate 2: DMI Cross Trend (DI+/DI- Crossover + EMA200)

**Loop:** 14
**Date:** 2026-06-28
**Source:** Free search (Sunday) — Investopedia, TradingView DMI strategy docs

## Concept

The **Directional Movement Index (DMI)** consists of three lines:
- **DI+**: measures upward price movement strength
- **DI-**: measures downward price movement strength  
- **ADX**: smoothed average of |DI+ - DI-| / (DI+ + DI-), measures trend strength (directionless)

**Key insight:** Previous loops tested ADX-threshold strategies (MacdAdxTrend in Loop 5, KeltnerBreakoutADX in Loop 2) — these all failed on 4h because ADX > 25 requires 14+ bars = 56+ hours of established trend before entry. The DI+/DI- crossover is purely directional and fires MUCH earlier.

## Entry Conditions (2 total)

1. **DMI crossover:** DI+(14) crosses above DI-(14) → bullish directional movement
2. **EMA200 trend filter:** Close > EMA(200) → only trade in uptrend

## Exit

DI+(14) crosses below DI-(14) → exit long

## Why This Should Work

- **DI crossover ≠ ADX threshold** — DI+/DI- cross fires at the start of directional movement, not after trend is "confirmed strong" by ADX > 25. This eliminates the 4h lag problem.
- **2 conditions exactly** — satisfies the proven template
- **No ADX dependency** — unlike Loop 2 (KeltnerBreakoutADX) and Loop 5 (MacdAdxTrend), this strategy does NOT require ADX > threshold. Pure directional cross.
- **Direct trend measurement** — DI+ and DI- measure actual price movement direction using True Range, not derived oscillator values
- **Should work on 4h** — since crossover happens at trend inception, not after 56-hour confirmation period

## Anti-Pattern Check

- ✅ Not mean reversion
- ✅ Not ≥3 AND conditions (2 conditions: DI cross + trend filter)
- ✅ Not candle-pattern based
- ✅ Not CLV-based  
- ✅ Not Ichimoku
- ✅ Not ADX-threshold (the key differentiation from prior failures)

## Parameters

| Param | Value | Rationale |
|-------|-------|-----------|
| `di_period` | 14 | Wilder's standard — balances signal speed vs noise |
| `trend_period` | 200 | Standard EMA trend filter |
| `min_bars` | 200 | Allow DI to stabilize |

## Expected Trade Count

- 1h: 100-200 trades/year (DI crosses are frequent on 1h)
- 4h: 30-70 trades/year (should exceed 30-trade gate since no ADX lag)

## Risk

DI crossover alone may generate whipsaw in ranging markets. The EMA200 trend filter should suppress most false signals in downtrends, but sideways markets with close > EMA200 may produce noise entries. The 2-condition template has proven this is acceptable risk (81% pass rate across loops).
