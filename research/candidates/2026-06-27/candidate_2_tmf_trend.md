# Candidate: TMF Trend (Twiggs Money Flow)

**Date:** 2026-06-27
**Loop:** 27
**Source:** Incredible Charts / TradingView (Twiggs Money Flow indicator)

## Strategy Overview

Twiggs Money Flow (TMF) zero-cross + EMA200 trend filter — a 2-condition volume-weighted money flow strategy.

TMF is a volume-weighted money flow indicator that improves on Chaikin Money Flow (CMF, tested Loop 14) by using True Range normalization instead of High-Low range, and Wilder smoothing instead of simple sum. The True Range denominator makes it more ETH-robust by downweighting wick-driven false volume.

## Entry Logic (2 conditions)

1. **TMF zero-cross**: TMF(21) crosses above 0 → long entry; crosses below 0 → short entry
2. **EMA200 trend filter**: Only enter long when close > EMA200; only short when close < EMA200

## Exit Logic

- Exit when TMF crosses back below 0 (from long) or above 0 (from short)
- Stop loss: 2× ATR(14)
- Take profit: 3× ATR(14)

## TMF Formula

```
TMF = EMA(volume * (2*dm - tr) / tr, 21) / EMA(volume, 21) * 100

where:
  dm = close - open (directional movement)
  tr = max(high-low, |high-prev_close|, |low-prev_close|) (True Range)
```

Key differences from CMF:
- Uses True Range (not High-Low range) → better handles gap-driven bars
- Uses Wilder EMA smoothing (not simple sum) → less volatile, fewer false zero-crosses
- Per-bar normalization → doesn't accumulate ETH noise like OBV/A/D Line

## Why This Might Work

1. **Volume-weighted with TR normalization**: The True Range denominator handles ETH's wick-heavy bars better than High-Low range (CMF's failure mode on ETH)
2. **EMA smoothing (not cumulative)**: Unlike OBV/A/D Line which accumulate ETH noise, TMF resets normalization per-bar — avoiding the cumulative-accumulation OOS catastrophe
3. **Proven family**: Volume-weighted money flow has been successful on BTC (ForceIndex Loop 10, MFI Loop 14, CMF Loop 14). TMF adds TR normalization for ETH robustness
4. **2 conditions only**: Zero-cross (1) + trend direction (2)

## Expected Trade Count

- BTC 1h: 80-150 trades
- BTC 4h: 30-45 trades
- ETH 1h: 70-130 trades
- ETH 4h: 25-40 trades

## Risks

- 21-bar Wilder smoothing adds ~10-bar effective lag — borderline for 4h trade count
- TMF normalization per bar might still be noisy on ETH 1h
- Wilder EMA is slower than regular EMA — fewer signals than CMF (which used regular EMA)

## Parameters

```python
DEFAULT_PARAMS = {
    "tmf_period": 21,          # TMF lookback period
    "trend_period": 200,       # EMA trend filter
    "atr_period": 14,          # Stop loss ATR
    "stop_mult": 2.0,          # Stop loss multiplier
    "tp_mult": 3.0,            # Take profit multiplier
    "min_bars": 200,           # Minimum bars for warmup
}
```

## Anti-Pattern Check

- ✅ 2 AND conditions (TMF zero-cross + EMA trend)
- ✅ No consolidation detection
- ✅ No candle pattern recognition
- ✅ No CLV/position-gating
- ✅ Volume-weighted → ETH-robust indicator family
- ✅ Per-bar normalization → no cumulative accumulation (avoids OBV/A/D Line ETH OOS trap)
- ⚠️ Wilder smoothing (21 bars) — monitor 4h trade count
- ⚠️ New indicator not previously tested — no direct family precedent
