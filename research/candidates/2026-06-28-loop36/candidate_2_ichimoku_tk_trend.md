# Candidate: Ichimoku TK Cross Trend

**Date:** 2026-06-28
**Loop:** 36
**Source:** Directly suggested by patterns.md anti-pattern (Loop 9 IchimokuCloud failure)

## Strategy Idea

Loop 9's IchimokuCloud failed because the dual cloud span filter (price > Span A AND price > Span B) created a disguised 3-condition entry. The anti-pattern explicitly noted: "use only TK cross as a standalone trigger OR cloud as standalone trend filter — never both."

This strategy implements TK cross (Tenkan-sen crosses above Kijun-sen) as the entry trigger with a simple EMA(200) trend filter — exactly 2 conditions, no cloud.

## Entry Conditions (Exactly 2)
1. **Tenkan-sen > Kijun-sen** (TK bullish cross) — momentum direction confirmed
2. **Close > EMA(200)** — uptrend filter

Exit: Tenkan-sen crosses below Kijun-sen (TK bearish cross) or trend violated.

## Why Novel
- IchimokuCloud was tested with all 3 conditions and failed (3/4 combos)
- This removes the cloud filter, converting a 3-condition strategy to 2 conditions
- TK cross alone should generate significantly more signals than TK+cross+cloud
- Directly implements patterns.md recommendation

## Anti-Pattern Check
- ✅ Not ≥3 conditions (exactly 2 — TK cross + trend)
- ✅ No cloud filter (removed Span A and Span B conditions)
- ✅ No CLV, candle patterns, adaptive indicators
- ✅ Fixed Ichimoku parameters (9/26), only TK components used
- ✅ Works on 1h primarily; 4h will likely have trade scarcity with 26-period Kijun

## Expected Parameters
```python
DEFAULT_PARAMS = {
    "tenkan_period": 9,     # Standard Ichimoku
    "kijun_period": 26,     # Standard Ichimoku
    "trend_period": 200,    # EMA trend filter
    "min_bars": 200,
}
```

## Expected Trade Count
Loop 9's full IchimokuCloud produced 84 trades on BTC 1h. Without the cloud filter blocking 60-70% of signals, this should produce 120-200 trades/year on 1h. 4h will be sparse (standard limitation).

## Risk Note
Loop 9's full IchimokuCloud on BTC 1h had 84 trades but negative Sharpe (-0.97). The TK cross alone may actually be too whippy without the cloud filter. But the 2-condition template with trend filter is the right test — if it fails, we learn whether the whipsaw comes from TK cross itself or from the cloud gating.
