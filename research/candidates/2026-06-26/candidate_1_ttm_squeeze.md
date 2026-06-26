# Candidate 1: TTMSqueezeTrend

**Date:** 2026-06-26
**Source:** GitHub trending — academic quant research adaptation
**Indicator Family:** TTM Squeeze (Bollinger/Keltner volatility contraction) + CCI momentum

## Strategy Concept

**TTM Squeeze** detects volatility contraction: when Bollinger Bands (20,2) contract INSIDE Keltner Channels (20,1.5), the market is "squeezing" — building potential energy for a directional breakout. When the squeeze fires (BB exits KC), paired with CCI momentum direction, the entry is timed at the beginning of volatility expansion.

### Signal Logic

- **Long entry:** BB inside KC (squeeze ON) AND CCI(20) > 0
- **Short entry:** BB inside KC (squeeze ON) AND CCI(20) < 0
- **Long exit:** Squeeze OFF (BB exits KC) OR CCI(20) < -50
- **Short exit:** Squeeze OFF OR CCI(20) > 50
- **Stop loss:** ATR(14) * 2 trailing

### Conditions: 2 total
1. Squeeze state (BB width < KC width) — volatility contraction
2. CCI direction — momentum confirmation

## Why This Could Work

- **Novel indicator family:** TTM Squeeze never tested across 15+ research loops
- **2 conditions exactly:** Squeeze + CCI. No hidden gates — BB/KC are simple MAs (no deep smoothing)
- **Breakout-adjacent:** Squeeze signals are volatility-contraction events that precede breakouts — similar mechanics to proven breakout families (DualThrust, RangeExpansion, ChannelBreakout)
- **CCI proven:** CCI passed 3/4 main gate (Loop 15), works on both 1h (154 trades) and 4h (30 trades)
- **4h viable:** CCI is the only smoothed oscillator to clear 4h gate (Loop 15). Squeeze detection uses 20-bar MAs — acceptable for 4h.
- **ETH-compatible:** CCI is normalized 0-100, not raw price-extreme. Should survive ETH's fragmented liquidity better than Elder Ray/Aroon.

## Anti-Patterns Avoided
- ✅ ≤2 AND conditions (squeeze state + CCI direction)
- ✅ No deep smoothing (BB/KC = 1-layer, CCI = 1-layer SMA)
- ✅ No raw price-extreme (CCI is normalized)
- ✅ No efficiency ratio or candle pattern gates
- ✅ No hysteresis or regime switching
- ✅ Breakout-adjacent (4h viable)

## Risk Factors
- Squeeze ON state may persist for many bars → fills may cluster. Mitigation: CCI direction provides entry timing.
- 4h squeeze events may be rarer than 1h — similar to BB %B finding (Loop 11: 36-50 4h trades). Acceptable if ≥30.
- CCI on ETH 4h produced 28 trades (Loop 15) — 2 short of gate. Squeeze filter may reduce further. Monitor closely.

## Parameters (Initial)
```python
DEFAULT_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "kc_period": 20,
    "kc_mult": 1.5,
    "cci_period": 20,
    "cci_entry": 0,          # CCI > 0 for long, < 0 for short
    "cci_exit_long": -50,    # Exit long if CCI < -50
    "cci_exit_short": 50,    # Exit short if CCI > 50
    "atr_period": 14,
    "trailing_mult": 2.0,
    "trend_filter": False,   # No extra trend filter — CCI handles direction
}
```

## Similar Strategies (for comparison)
| Strategy | Entry 1 | Entry 2 | 4h? | ETH? |
|----------|---------|---------|-----|------|
| TTMSqueezeTrend | Squeeze ON | CCI > 0 | Yes (hoped) | Yes (hoped) |
| ChannelBreakoutRSI | Channel breach | RSI > 50 | Failed (4h) | Failed (ETH) |
| RangeExpansion | Channel breach | ATR > 1.5x | Yes (30-80) | Yes |
| DualThrust | Range breakout | Close direction | Yes (136) | Yes (full OOS) |
| CCITrend | CCI > 100 | EMA200 trend | Yes (30) | Close (28) |
