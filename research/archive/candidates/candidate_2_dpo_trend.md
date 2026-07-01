# Candidate 2: DPOTrend

**Date:** 2026-06-26
**Source:** GitHub trending — classic indicator revival
**Indicator Family:** Detrended Price Oscillator (DPO) + EMA200 trend filter

## Strategy Concept

**DPO (Detrended Price Oscillator)** removes the trend component from price data by time-shifting the close prices backward (`period/2 + 1` bars) before computing a SMA difference. This mathematically eliminates SMA lag — the time-shift centers the moving average so it responds to the CURRENT bar's position, not the average of the past N bars. Unlike standard oscillators (RSI, Stochastic, CMO, CCI) which smooth the signal, DPO uses a time-domain transformation that preserves signal frequency while eliminating lag.

Why DPO matters: Every lag-based oscillator (MACD, Stochastic %K/%D, RSI, CMO with signal SMA) introduces ~N/2 bars of delay. DPO is the ONLY oscillator that eliminates this delay entirely via time-shifting rather than smoothing.

### Signal Logic

- **Long entry:** DPO(20) crosses above 0 AND close > EMA200
- **Short entry:** DPO(20) crosses below 0 AND close < EMA200
- **Long exit:** DPO(20) crosses below 0
- **Short exit:** DPO(20) crosses above 0
- **Stop loss:** ATR(14) * 2 trailing

### Conditions: 2 total
1. DPO zero-cross (signal direction)
2. EMA200 trend filter (trend context)

## Why This Could Work

- **Novel indicator family:** DPO never tested across 15+ research loops — this is a genuine gap in the research coverage
- **Zero smoothing:** DPO has exactly 0 EMA smoothing layers — maximum ETH compatibility per "Smoothing Depth Penalty" (each layer costs 0.3-0.5 Sharpe on ETH; DPO has 0 layers)
- **No hidden gates:** The time-shift is a mathematical transformation, not a quality filter or gate. It preserves all signal density.
- **Frequent signals:** DPO zero-cross frequency should match MACD or better (since DPO eliminates the SMA lag, it crosses more frequently). Expected 100-300 trades/year on 1h, 30-60 on 4h.
- **Similar to Fisher Transform** (Loop 18, best ETH-compatible oscillator): Both use mathematical transformations (Fisher = Gaussian, DPO = time-shift) rather than smoothing to enhance signal quality.
- **2 conditions exactly** — the proven template.

## Anti-Patterns Avoided
- ✅ ≤2 AND conditions (DPO cross + trend)
- ✅ Zero smoothing layers (ETH-optimal by the Smoothing Depth Penalty curve)
- ✅ No raw price-extreme (DPO uses close, not high/low)
- ✅ No efficiency ratio or candle pattern gates
- ✅ No hysteresis or regime switching
- ✅ Normalized around zero (threshold-free like Fisher Transform)

## Risk Factors
- DPO is mathematically close to MACD(close, 20, ∞) with a time-shift. If MACD-like behavior dominates, signals may be too sparse on 4h (MACD+ADX on 4h produced only 12-65 trades — Loop 5). Mitigation: DPO's time-shift eliminates SMA lag, should produce more frequent crossovers than MACD.
- ETH 1h: DPO's zero-cross frequency on choppy ETH 1h may produce whipsaw entries. EMA200 trend filter mitigates.
- 4h OOS: Same mathematical constraint as all crossover/oscillator strategies on 4h (730 OOS bars). DPO at period=20 means 5 bars of time-shift + 20 bars of SMA = 100 hours effective window on 4h. May be too slow for OOS validation.

## Parameters (Initial)
```python
DEFAULT_PARAMS = {
    "dpo_period": 20,       # Standard — matches lookback sweet spot
    "trend_period": 200,    # EMA200 trend filter (proven across 10+ loops)
    "atr_period": 14,       # Trailing stop ATR period
    "trailing_mult": 2.0,   # Trailing stop multiplier
    "use_trailing_stop": False,  # False → exit on DPO reverse cross only
}
```

## Mathematical Note
```
DPO(t) = close(t - period/2 - 1) - SMA(close, period)[t]
```
The forward-shift of the close means: "what was the close doing relative to the SMA, centered on that point in time?" This is fundamentally different from:
- MACD: close vs EMA comparisons WITH lag
- CCI: deviation from SMA in units of mean absolute deviation
- CMO: sum-based momentum (normalized but with N-bar horizon)
- Stochastic: position within N-bar range (normalized but range-dependent)

## Similar Strategies
| Strategy | Indicator | Smoothing | Lag | ETH OOS |
|----------|-----------|-----------|-----|---------|
| DPOTrend | DPO | 0 layers | 0 bars (time-shifted) | ? (untested) |
| FisherTransformTrend | Fisher | 0 layers | 0 bars (instantaneous) | ✓ OOS=2.23 |
| CCITrend | CCI | 1 layer (SMA) | ~7 bars | ✗ OOS=-0.93 |
| CMOTrend | CMO | 1 layer (signal SMA) | ~5 bars | ✗ OOS=-0.08 |
| StochRSITrend | Stochastic | 2 layers (%K/%D) | ~10 bars | ✗ |
| KST/TRIX | KST/TRIX | 3-4 layers | ~15-20 bars | ✗✗ |
