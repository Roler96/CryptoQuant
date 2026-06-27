# Candidate 1: Chaikin Oscillator Trend

**Date:** 2026-06-28
**Loop:** 31
**Source:** Internal pattern mining (cumulative volume family extension)

## Rationale

Chaikin Oscillator = EMA(3, A/D Line) - EMA(10, A/D Line) — measures the *momentum* of accumulation/distribution, not just the direction. This extends the proven cumulative volume family (OBV 4/4, ADLine 4/4 main gate) by adding an acceleration layer.

OBV and A/D Line worked because cumulative volume smooths ETH noise and generates sufficient 4h trades. Chaikin Oscillator zero-cross should fire MORE frequently than OBV SMA crossover because it measures rate-of-change of the accumulation line — earlier signal, higher trade count.

## Strategy Design

```
Entry (LONG):  Chaikin Oscillator crosses above 0 AND Close > EMA200
Entry (SHORT): Chaikin Oscillator crosses below 0 AND Close < EMA200
Exit:          Chaikin Oscillator crosses opposite direction OR trailing stop at 2× ATR(14)

Conditions: 2 (zero-cross + EMA200 trend)
```

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| chaikin_fast | 3 | Standard Chaikin short period |
| chaikin_slow | 10 | Standard Chaikin long period |
| trend_period | 200 | Proven EMA200 trend filter |
| atr_period | 14 | Standard ATR |
| trailing_mult | 2.0 | Standard trailing stop |
| min_bars | 150 | Allow sufficient warmup |

## Expected Performance

- **1h BTC:** 120-200 trades, Sharpe 1.5-2.5 (similar to OBV/ADLine)
- **1h ETH:** 120-200 trades, Sharpe 0.5-1.5 (Chaikin smoother than per-bar volume, may survive ETH better)
- **4h BTC:** 30-50 trades, Sharpe 1.0-2.0 (momentum of accumulation may fire faster than OBV SMA cross)
- **4h ETH:** 25-40 trades, Sharpe 0.5-1.5

## Anti-Pattern Check

- ✅ 2 AND conditions only
- ✅ Not a raw price-extreme indicator (safe for ETH)
- ✅ Not triple-smoothed (only 3/10 EMA on A/D line = light smoothing)
- ✅ Cumulative volume family (75% pass rate across 16 combos)
- ✅ Not signal-sparse (zero-cross of EMA difference fires frequently)
- ✅ Not previously tested
