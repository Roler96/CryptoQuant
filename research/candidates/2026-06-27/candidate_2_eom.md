# Candidate: EOM Trend (Ease of Movement)

## Source
Recommended in patterns.md (Loop 24): "Future strategies should explore: ... Ease of Movement crossover"
Date: 2026-06-27 (Saturday — quant blog rotation)

## Strategy Description
Uses Ease of Movement (EOM) indicator as primary entry trigger. EOM measures how easily price moves per unit of volume — it's a volume-weighted momentum indicator that differs from Force Index (price change × volume) and OBV (cumulative volume × sign). Entry on EOM zero-cross with EMA200 trend filter.

## Entry Logic
- **Long:** EOM crosses above 0 AND close > EMA200
- **Short:** EOM crosses below 0 AND close < EMA200

## Exit Logic
- Exit on EOM reverse zero-cross (mirror of entry)

## Conditions
- 2 total AND conditions: EOM zero-cross + EMA200 trend filter
- EOM formula: ((High+Low)/2 - prev(High+Low)/2) / (Volume / (High-Low))
- Standard EOM smoothed with 14-period SMA

## Why This Is Promising
1. **Genuinely novel but recommended** — recommended in patterns.md but never tested across 24 loops
2. EOM combines price movement AND volume in a unique way:
   - Numerator: midpoint change (raw price movement)
   - Denominator: volume / range (normalized volume per unit of price movement)
   - Result: high EOM = efficient price movement (small volume moves price far), low EOM = inefficient
3. The denominator normalization (volume/range) is unique — not used by any other tested volume indicator
4. 2-condition template, avoiding all known anti-patterns
5. Joins the volume-weighted indicator family which is proven ETH-robust (ForceIndex, MFI, OBV)

## Anti-Pattern Checks
- ✅ 2 conditions (not ≥3)
- ✅ Not consolidation-detection (no "wait then breakout")
- ✅ Not raw price-extreme on ETH (EOM uses midpoint, smooths via SMA)
- ✅ Not triple-smoothed (single SMA)
- ✅ Volume-weighted family (ETH-robust)
- ✅ Entry is frequent signal generator (zero-cross), not rare event detector
- ✅ Not candle pattern, CLV, Heikin-Ashi, VWAP, or Ichimoku

## Parameters
```python
DEFAULT_PARAMS = {
    "eom_period": 14,
    "trend_period": 200,
}
```

## Test Matrix
| Symbol | Timeframe | Expected trades |
|--------|-----------|-----------------|
| BTC/USDT | 1h | 70-140 |
| BTC/USDT | 4h | 25-40 |
| ETH/USDT | 1h | 60-130 |
| ETH/USDT | 4h | 20-35 |

## Notes
- EOM is from Richard Arms' "Volume Cycles in the Stock Market" — a classic indicator with good academic pedigree
- EOM can have extreme values when volume is very low — the 14-period SMA smooths outliers
- 4h trade count may be marginal (similar to other volume-weighted indicators at 14-20 trades). Consider eom_period=10 if 4h trade count is insufficient
- EOM zero-cross is equivalent to smoothed midpoint change crossing zero — simpler than it sounds
