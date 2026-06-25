# Candidate 1: KeltnerBreakoutADX

**Date:** 2026-06-25
**Source:** Keltner Channel Breakout Strategy (PyQuantLab / QuantVPS)
**Type:** Trend-following breakout

## Hypothesis
Keltner Channel breakouts confirmed by ADX trend strength and volume expansion
capture directional moves with fewer false signals than simple EMA crosses.

## Anti-Pattern Check
- ✅ NOT pure mean reversion (trend-following breakout)
- ✅ NOT signal-sparse (breakout + ADX + volume = 3 conditions, reasonable)
- ✅ Different from EMACrossATRFilter (breakout logic vs. cross-over logic)

## Strategy Logic

### Indicators
- Keltner Channel: 20-period EMA ± (2.0 × ATR(14))
- ADX(14): trend strength > 25 = trending market
- Volume ratio: current volume / 20-period SMA volume > 1.2

### Entry (Long)
1. Close > KC upper band
2. ADX > 22 (trending market)
3. Volume ratio > 1.2 (volume confirmation)

### Entry (Short)
1. Close < KC lower band
2. ADX > 22
3. Volume ratio > 1.2

### Exit
- Close crosses back below/above KC middle band (EMA)
- Stop-loss: 2.5 × ATR from entry
- Take-profit: None (let trend run)

### Signal Convention
- 1 = long, -1 = short, 0 = flat

## Parameters (Default)
```python
{
    "kc_period": 20,      # EMA period for Keltner Channel
    "kc_multiplier": 2.0, # ATR multiplier for band width
    "atr_period": 14,     # ATR lookback
    "adx_period": 14,     # ADX lookback
    "adx_threshold": 22,  # Minimum ADX for trend confirmation
    "vol_period": 20,     # Volume SMA period
    "vol_threshold": 1.2, # Volume ratio threshold
    "stop_atr_mult": 2.5, # Stop-loss in ATR multiples
}
```

## Expected Characteristics
- **Target trades/year:** 50-200
- **Market regime:** Trending markets (ADX > 22)
- **Risk:** Breakout fakeouts mitigated by ADX + volume confirmation

## Key Risk
- In choppy/ranging markets, few signals (ADX filter eliminates these)
- May underperform in low-volatility environments
