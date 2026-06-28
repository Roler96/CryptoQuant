# Candidate 2: MFI Trend (mfi_trend)

## Source
Sunday free search — Money Flow Index, volume-weighted RSI oscillator normalized to 0-100. Never tested in any previous loop.

## Strategy Concept
**MFI threshold crossover + EMA200 trend filter (2 conditions)**

The Money Flow Index (MFI) is a volume-weighted RSI that oscillates between 0-100. It combines price direction with volume intensity — detecting whether money is flowing into or out of an asset. Unlike Force Index (which multiplies volume × price change and is unbounded), MFI is normalized to 0-100, making it timeframe/symbol agnostic — the key property that made BB %B universally robust in Loop 11.

### Entry Logic
- **Long:** MFI crosses above 50 AND close > EMA200
- **Short:** MFI crosses below 50 AND close < EMA200

### Exit Logic
- MFI crosses back through 50 (reverse signal)
- Stop-loss: 2× ATR(14) trailing
- Take-profit: 3× ATR(14)

### Default Parameters
```python
DEFAULT_PARAMS = {
    "mfi_period": 14,
    "mfi_threshold": 50,
    "trend_period": 200,
    "atr_period": 14,
    "stop_mult": 2.0,
    "take_profit_mult": 3.0,
}
```

## Why This Should Work
- Exactly 2 conditions (proven template — 80.4% pass rate)
- **Normalized indicator (0-100)** — this is the key insight from Loop 11: normalized indicators (%B, Stochastic) achieve universal parameter robustness across all 4 combos. MFI shares this property.
- Volume-weighted — incorporates volume information WITHOUT gating entry (multiplies signal strength rather than filtering). Loop 10 showed Force Index (volume × price change) succeeded where CLV (position-based) failed.
- MFI crosses 50 frequently — the middle line is crossed ~5-10× more often than overbought/oversold thresholds (80/20). Should generate 50-200 trades/year.
- Unlike Force Index (unbounded, requires parameter tuning), MFI's 0-100 normalization means mfi_threshold=50 works identically across BTC/ETH × 1h/4h with zero parameter changes.

## Anti-Pattern Check
- ✅ Not ≥3 AND conditions (exactly 2)
- ✅ Not mean reversion (trend filter + momentum oscillator = trend following)
- ✅ Not CLV-based or candle pattern recognition
- ✅ Not percentile-gated volume filter (MFI uses continuous volume weighting, not binary gate)
- ✅ Not Ichimoku (no disguised AND gates)
- ✅ Not acceleration-based — MFI is an oscillator, should work independently of 4h acceleration problems
- ✅ Normalized indicator — should scale to 4h (key insight from Loop 11 BB %B success)

## Distinction from Previous Strategies
- Not Force Index (unbounded, volume×price) — MFI is bounded 0-100 with formal money flow calculation
- Not RSI (no volume) — MFI includes volume in raw money flow
- Not Stochastic (price position in range) — MFI uses typical price × volume flow
- Not BB %B (position within bands) — MFI measures cumulative money flow pressure
- Not OBV (cumulative volume delta) — MFI is a bounded oscillator with overbought/oversold semantics
