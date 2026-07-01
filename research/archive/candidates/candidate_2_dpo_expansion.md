# DPOExpansion — Detrended Price Oscillator + ATR Expansion

**Source:** Classic technical analysis (DPO by William Blau); arXiv context — trend-following strategies with volatility confirmation are the dominant theme across all major crypto quant papers (2511.00665, 2510.07943, 2602.11708)

**Date:** 2026-06-29
**Candidate ID:** candidate_2_dpo_expansion

## Strategy Summary

DPO (Detrended Price Oscillator) removes the long-term trend component from price by comparing close to a centered moving average, isolating shorter-term cycles on top of the trend. Combined with ATR expansion confirmation (the most proven filter — 7/7 strategies with ≥75% pass rate), this creates a 2-condition momentum-in-context entry.

## Signal Logic

- **Entry Long:** DPO(20) crosses above 0 AND ATR(14) > SMA(ATR(14), 50)
- **Entry Short:** DPO(20) crosses below 0 AND ATR(14) < SMA(ATR(14), 50) (or use reversed DPO + ATR expansion for short)
- **Exit:** DPO(20) crosses back across 0

## Key Formula

```
DPO = Close - SMA(Close, 11).shift(-11)    # centered MA, N/2+1 = 11 for period 20
# DPO > 0 means current close is above the SMA centered on this bar
# Effectively: "is price accelerating above its historical centered average?"
```

## Why This Should Work

1. **DPO is NOT a smoothed crossover:** Unlike MACD/Stochastic/EMA cross (which use multi-bar smoothing), DPO uses a single centered MA — one level of smoothing, not two. This preserves signal density following the "≤1 EMA layer for ETH" rule (from Loop 15)
2. **ATR expansion filter:** The single most proven confirmation filter — 6 strategies have achieved perfect 4/4 main gate pass with ATR expansion (EMACrossATRFilter, RangeExpansionBreakout, InsideBarBreakout, BBPercentBVolatility, EMASlopeATR, SwingPivotBreakout). DPO + ATR expansion is a novel combination of this filter with a new entry family.
3. **2 conditions exactly:** Clean template, no hidden gates
4. **Centered perspective:** DPO's backward-looking centered MA provides a different signal domain than all 37+ loops tested — it answers "is price above where its historical centered average would predict?" rather than "is momentum increasing?"
5. **BTC 1h potential high:** DPO zero-crosses should be frequent (like CCI extreme readings) while the ATR filter eliminates noise crosses

## Risk Factors

1. **4h trade scarcity (primary risk):** DPO(20) on 4h = 80-hour lookback equivalent. Zero-cross events may be sparse. However, DPO is a single-SMA indicator (not double-smoothed), so signal density should be better than MACD/Stochastic/CMO on 4h
2. **ETH noise:** Like LinearRegressionSlope (Loop 37), a centered-statistical indicator may misread ETH's fragmented-liquidity noise as genuine trend
3. **DPO novelty risk:** DPO was designed for cycle identification, not trend following. DPO > 0 may simply be a noisy proxy for Close > SMA — the ATR filter is the saving grace here

## Parameters

- `dpo_period`: 20 (standard Blau setting, ~1 month of daily data equivalent)
- `atr_period`: 14 (standard)
- `atr_ma_period`: 50 (long ATR baseline for clean expansion signals)
- `min_bars`: 250 (similar to EMV strategy)

## Anti-Pattern Check

- ✅ NOT a raw price-extreme indicator
- ✅ NOT ≥3 AND conditions (DPO cross + ATR expansion = 2)
- ✅ NOT candle pattern-based
- ✅ NOT triple-smoothed (single SMA)
- ✅ NOT Ichimoku/CLV/Efficiency Ratio family
- ⚠️ ETH OOS risk (all strategies face this — ATR expansion is our best defense)
- ⚠️ 4h trade scarcity risk (but DPO's single-layer SMA is better than double-smoothed oscillators)
- ✅ Uses ATR expansion — the universal filter (6/6 perfect sweeps)

## Comparison to Existing Strategies

| Strategy | Primary Entry | Filter | 4h Pass? | ETH OOS? |
|----------|--------------|--------|----------|----------|
| EMACrossATRFilter | EMA cross | ATR expansion | Yes | Yes (ETH 1h) |
| RangeExpansionBreakout | Channel breakout | ATR expansion | Yes | Yes |
| BBPercentBVolatility | %B threshold | ATR expansion | Yes | No (ETH 4h) |
| EMASlopeATR | EMA slope | ATR expansion | Yes | Yes (ETH 1h) |
| **DPOExpansion** | **DPO zero-cross** | **ATR expansion** | **?** | **?** |
