# EOMTrend — Ease of Movement Trend Following

**Source:** Richard Arms' Ease of Movement (EMV) indicator; discussed in volume-flow momentum literature on arXiv (2512.12924 "Flow Momentum" concept — combining price momentum with confirming order flow)

**Date:** 2026-06-29
**Candidate ID:** candidate_1_eom_trend

## Strategy Summary

Ease of Movement (EMV) measures how easily price moves per unit of volume. When EMV is positive, price is moving up easily (low volume required per unit of price change) — indicating genuine buying pressure. When EMV crosses above zero with trend confirmation, enter long.

## Signal Logic

- **Entry Long:** EMV(14) crosses above 0 AND Close > EMA(200)
- **Entry Short:** EMV(14) crosses below 0 AND Close < EMA(200)
- **Exit:** EMV(14) crosses back across 0 (reverse signal)

## Key Formula

```
EMV = ((High + Low) / 2 - (PrevHigh + PrevLow) / 2) / (Volume / (High - Low))
EMV_smoothed = EMA(EMV, 14)
```

## Why This Should Work

1. **Volume-normalized:** EMV divides price movement by volume-per-unit-range — when price moves easily on low volume, it suggests genuine directional pressure (not noise/liquidity artifact)
2. **2 conditions exactly:** EMV zero-cross + EMA200 trend filter — clean template
3. **ETH potential:** Volume normalization may provide natural ETH noise resistance (already proven: ForceIndex, MFI, CMF all use volume-weighting and are among the few ETH-robust strategies)
4. **Novel architecture:** No other strategy in 37+ loops uses EMV as an entry trigger — genuinely unexplored indicator family
5. **Self-scaling:** EMV normalizes across volatility regimes through the volume term — doesn't need per-combo parameter tuning

## Risk Factors

1. **4h signal sparsity:** Volume-based indicators (CMF: 19-20, MFI: 14-15, ForceIndex: ~20) have all struggled with 4h trade count. Likely EMV will be ≤30 trades on 4h
2. **Zero-cross frequency:** EMV zero-cross events depend on bar-level volume dynamics — crypto volume is noisy, which could produce either too many false crosses or too few genuine ones
3. **Commission sensitivity:** Volume-based metrics can generate many small-edge trades — commission sweep needed

## Parameters

- `emv_period`: 14 (standard Arms setting, balanced noise/signal)
- `trend_period`: 200 (EMA trend filter)
- `min_bars`: 250 (long enough for signals to develop given 2 conditions)

## Anti-Pattern Check

- ✅ NOT a raw price-extreme indicator (uses midpoint, not High/Low only)
- ✅ NOT ≥3 AND conditions
- ✅ NOT candle pattern-based
- ✅ NOT triple-smoothed (single EMA smoothing)
- ✅ NOT Ichimoku/CLV/Efficiency Ratio family
- ⚠️ Volume-based — 4h trade count risk (known anti-pattern for volume families)
- ⚠️ ETH OOS risk (but volume-weighting is the best defense against ETH OOS curse)
