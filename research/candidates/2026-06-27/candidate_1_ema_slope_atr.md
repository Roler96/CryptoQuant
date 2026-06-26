# Candidate: EMASlopeATR

**Discovered:** 2026-06-27
**Source:** Quant blog synthesis — EMA slope as trend-strength proxy + ATR expansion
**Loop:** 13

## Hypothesis

Trend *steepness* matters more than trend *direction* for entry timing. An EMA(20) that is steepening
indicates trend acceleration — price is moving away from the mean at an increasing rate. Paired with
ATR expansion (volatility confirmation), this captures entries at the start of strong directional moves.

## Entry Logic (2 conditions)

1. **EMA slope acceleration**: EMA(20) slope_current > EMA(20) slope_5bars_ago
   - slope = EMA(20)[t] - EMA(20)[t-1]
   - Acceleration = slope > slope 5 bars ago
2. **ATR expansion**: ATR(14) > SMA(ATR(14), 50)
   - Same filter proven in Loops 5, 6, 11

## Exit Logic

- Signal zero-cross: EMA slope acceleration turns negative (deceleration)
- Or reverse signal for opposite direction

## Rationale

- EMA slope is a first-derivative measure — it reacts faster than EMA crossover (second-derivative)
- ATR expansion filters out low-volatility drift entries
- 2 total conditions, no hidden AND gates
- EMA(20) is short enough to generate 50-150 trades/year on 1h

## Anti-Pattern Check

- ✅ 2 conditions (not ≥3)
- ✅ Not CLV-based
- ✅ Not candle pattern-based
- ✅ Not Ichimoku
- ✅ Not ADX-dependent
- ✅ Uses ATR expansion (proven confirmation filter)
- ⚠️ Slope-based signal may be noisy on 4h (expected: 20-40 trades)
- ⚠️ May produce high trade count on ETH 1h (whipsaw risk due to ETH microstructure)

## Expected Trade Count

- BTC 1h: 80-150
- ETH 1h: 100-200
- BTC 4h: 25-45
- ETH 4h: 25-40

## Parameters (initial)

```python
DEFAULT_PARAMS = {
    "ema_period": 20,
    "slope_lookback": 5,
    "atr_period": 14,
    "atr_ma_period": 50,
}
```

## Next Steps

1. Implement in `research/backtest_ema_slope_atr.py`
2. Test with `tests/research/test_backtest_ema_slope_atr.py`
3. Backtest: BTC/ETH × 1h/4h × 365d
