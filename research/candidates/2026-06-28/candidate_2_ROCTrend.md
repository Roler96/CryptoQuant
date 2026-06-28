# Candidate: ROCTrend

**Date:** 2026-06-28
**Loop:** 30
**Status:** DISCOVER

## Strategy Overview

Raw Rate of Change (ROC) zero-cross as primary entry trigger, paired with EMA200 trend filter.

## Signal Logic

1. **Entry (long):** ROC(20) crosses above 0 AND close > EMA(200)
2. **Entry (short):** ROC(20) crosses below 0 AND close < EMA(200)
3. **Exit:** ROC crosses back across 0 (reverse signal)

## Why This Is Novel

- **ROC is raw momentum** — computes (close[t] - close[t-N]) / close[t-N] × 100. Unlike CMO (which normalizes by sum of up/down), RiskAdjustedMomentum (which divides by volatility), or Z-score momentum (which uses rolling std), ROC is the simplest possible momentum measure with zero normalization.
- All previous momentum strategies applied some form of normalization or smoothing before thresholding. ROC tests whether **the raw price change percentage** contains enough signal to profit in crypto markets.
- The EMA200 trend filter is the most common 2nd condition across successful strategies — this is a pure test of whether raw ROC adds value beyond the trend filter alone.

## Expected Properties

- **Trade count:** 60-150 on 1h, 15-30 on 4h (ROC zero-cross is moderately frequent; no ATR filter to reduce count)
- **Win rate:** 38-48% (raw momentum may be noisier than smoothed)
- **ETH risk:** Low smoothing (ROC has zero EMA layers) → avoids the smoothing-depth penalty. ETH 1h OOS likely still problematic per established pattern.
- **BTC expected Sharpe:** 0.8-2.0 on 1h

## Parameters

```python
DEFAULT_PARAMS = {
    "roc_period": 20,
    "trend_period": 200,
    "min_bars": 100,
}
```

## Anti-Pattern Check

- ✅ 2 conditions (ROC zero-cross + EMA200 trend)
- ✅ ROC zero-cross is mechanical and frequent
- ✅ No hidden smoothing gates (ROC is pure price change, zero smoothing)
- ✅ No normalization lag (no rolling std, no sum-based denominator)
- ⚠️ No ATR or volatility filter — raw momentum may be noisy on 1h
- ⚠️ 4h trade count at risk — ROC(20) on 4h = 80-hour lookback, similar to other crossover failures
