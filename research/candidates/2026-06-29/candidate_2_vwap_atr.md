# Candidate 2: VWAP Deviation + ATR Expansion

**Date:** 2026-06-29
**Source:** arxiv 2606.00060 (VWAP deviation used as ML feature for BTC trading) + arxiv 2602.00776 (VWAP in crypto microstructure). VWAP is a classic institutional benchmark NEVER tested as a primary entry signal in this project.

## Strategy Concept

**VWAPATRTrend** — Enters when price crosses VWAP with ATR expansion confirmation. Combines volume-weighted fair-value benchmark (VWAP) with volatility expansion filter (ATR).

### Entry Signal
- **Long:** close crosses above VWAP(20) AND bar range > 1.5 × ATR(14)
- **Short:** close crosses below VWAP(20) AND bar range > 1.5 × ATR(14)
- **Exit:** close crosses back across VWAP (reverse cross)

### Key Ingredients
1. **VWAP (Volume-Weighted Average Price):** Rolling VWAP acts as a volume-weighted fair-value benchmark. Price crossing above VWAP signals institutional buying pressure; crossing below signals selling pressure.
2. **ATR expansion confirmation:** Bar range > 1.5 × ATR(14) — the proven expansion filter from RangeExpansionBreakout (Sharpe=3.19) and InsideBarBreakout (Sharpe=5.44).
3. **Total: 2 conditions** — obeys the 2-condition rule.

### Why This Could Work
- VWAP is fundamentally different from all previously tested entry mechanisms:
  - NOT a price-only crossover (EMA, MACD)
  - NOT an oscillator (RSI, Stochastic, CMO)
  - NOT a breakout (channel, inside bar, BB)
  - NOT a statistical estimator (OLS slope)
- VWAP incorporates volume as a **signal-strength multiplier** (not a gate) — the weighted average naturally dampens low-volume moves. This aligns with Loop 10's finding: "Volume-weighted momentum > position-based gating."
- Unlike CLV (which gates on bar position and kills trade count), VWAP is a continuous benchmark that crosses frequently — preserving the 50-200 trade/year sweet spot.
- ATR expansion is the proven #1 confirmation filter (ranked above RSI and volume-SMA in Loop 5).

### Anti-Pattern Compliance
- ✅ 2 conditions (VWAP cross + ATR expansion)
- ✅ Not a volume percentile gate (VWAP is a weighted average, not a threshold)
- ✅ Not CLV-based (VWAP is a benchmark, not a bar-position ratio)
- ✅ Not adaptive (fixed periods)
- ✅ Not candle pattern-based
- ✅ 1h timeframe avoids 4h crossover scarcity
- ✅ VWAP's volume weighting is multiplicative (signal strength), not gating (entry count)

## Parameters
```python
DEFAULT_PARAMS = {
    "vwap_period": 20,
    "atr_period": 14,
    "expansion_mult": 1.5,
}
```

## Expected Performance
- Target: 50-150 trades/year on 1h
- Expected Sharpe: 1.5-3.0 (VWAP is institutional-grade benchmark + ATR is proven filter)
- BTC expected to outperform ETH (consistent with all strategy families)
- 4h may work for VWAP cross (unlike smoothed crossovers, VWAP is an instantaneous benchmark) but trade count uncertain
- The 1.5x ATR multiplier is the proven sweet spot (Loops 5-6)

## Backtest Combinations
1. BTC/USDT 1h
2. BTC/USDT 4h
3. ETH/USDT 1h
4. ETH/USDT 4h
