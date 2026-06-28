# Candidate: HMA Crossover Trend (HMATrend)

**Date:** 2026-06-28
**Source:** 自由搜索 - Alan Hull (2005) HMA design paper + 49-strategy backtest article (dev.to, Mar 2026)
**Status:** Candidate

## Core Idea

Hull Moving Average (HMA) crossover with EMA200 trend filter. HMA was specifically designed to reduce lag while maintaining smoothness by using weighted moving average of WMA differences: HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n)). This produces a near-zero-lag moving average that preserves signal density — same benefit as ALMA's Gaussian offset, but achieved through a different mathematical mechanism.

## Signal Logic

- **Entry:** fast HMA crosses above slow HMA AND close > EMA200 → Long
- **Exit:** fast HMA crosses below slow HMA → Flat
- **Conditions:** 2 (HMA crossover + trend filter)

## Why This Should Work

1. HMA's weighting scheme (2× half-length WMA minus full-length WMA) counteracts lag without over-smoothing — mathematically different from ALMA's Gaussian offset but same zero-lag benefit
2. ALMA proved that low-lag crossovers can be 4h-viable (44 trades, Sharpe=1.97 BTC 4h). HMA should achieve similar 4h signal density
3. Crossover-based entry generates 100-250 trades/year on 1h — well within the 50-200 sweet spot
4. 2 conditions total — respects the proven template

## Anti-Pattern Check

- ✅ NOT signal-sparse (crossover generates abundant signals unlike percentile gates)
- ✅ NOT 3+ conditions (2 conditions: crossover + trend filter)
- ✅ NOT mean reversion (crossover is trend-following)
- ✅ NOT efficiency-ratio smoothed (HMA is fixed-weighting, unlike KAMA/PFE)
- ✅ NOT candle-pattern based (mechanical crossover, no bar structure dependency)

## Risks

- ETH 1h: HMA's reduced lag may amplify ETH microstructure noise (same issue as ALMA)
- 4h trade count may fall below 30 if periods are too long — use relatively short periods (fast=9, slow=21)
- HMA's weighting can produce overshoot in volatile bars — whipsaw risk

## Parameters

```python
DEFAULT_PARAMS = {
    "hma_fast": 9,      # Fast HMA period
    "hma_slow": 21,     # Slow HMA period  
    "trend_period": 200, # EMA trend filter period
    "min_bars": 200      # Minimum bars for warmup
}
```

## Expected Results

- BTC 1h: Sharpe 1.2-1.8, 150-250 trades
- ETH 1h: Sharpe 0.3-0.8 (ETH noise amplification risk), 150-250 trades
- BTC 4h: Sharpe 1.0-1.5, 30-50 trades (4h crossover viability test)
- ETH 4h: Sharpe 0.2-0.6 (ETH 4h hostile regime), 25-40 trades
