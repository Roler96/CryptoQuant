# Candidate 2: VIDYACrossoverExpansion

**Date:** 2026-06-28
**Source:** ArXiv Monday — ETIA paper (Springer, May 2026) mentions VIDYA as adaptive approach
**Status:** Candidate

## Strategy Concept

VIDYA Fast/Slow Crossover + ATR Expansion Confirmation

## Why This Could Work

1. **VIDYA is direction-aware adaptive smoothing.** Unlike KAMA (which uses Kaufman's Efficiency Ratio — a non-directional noise measure), VIDYA uses Chande Momentum Oscillator (CMO) as the efficiency ratio. CMO measures directional trend strength (sum of up moves / sum of absolute moves), meaning VIDYA smooths LESS in strong directional trends (faster response) and smooths MORE in choppy conditions (noise reduction). This is fundamentally different from both standard EMAs and KAMA.

2. **KAMA failed on 4h (12 trades), but because of ER-based adaptation.** Kaufman's ER measures noise, not direction — it can be high during both uptrends and downtrends. CMO-based adaptation preserves direction information, potentially generating crossovers even in noisy-but-directional markets where KAMA stays flat.

3. **Standard CMO already passed gate (Loop N, Sharpe=1.89).** If a static CMO + EMA200 works, a CMO-adapted EMA crossover should work even better — the adaptation is the differentiator, not the base oscillator.

4. **ATR expansion filter is the strongest confirmation.** Adding the proven ATR expansion filter makes this a clean 2-condition template: adaptive crossover + volatility expansion. No hidden AND gates, no regime switching.

5. **Different from all tried adaptive indicators.** KAMA (ER-based), MAMA (phase-based), ALMA (Gaussian), HMA (WMA-of-WMA), McGinley Dynamic (error-tracking). All failed on 4h. VIDYA uses directional momentum for adaptation — a genuinely different approach.

## Entry Conditions (2 AND conditions)

1. **VIDYA fast (short effective period) crosses ABOVE VIDYA slow (long effective period)** — momentum entry
2. **ATR expansion:** bar_range > rolling_percentile(ATR(14), window=50) at 80th percentile — volatility confirmation

## Exit Conditions

1. VIDYA fast crosses BELOW VIDYA slow — exit on signal reversal

## Risk Management

- ATR trailing stop (2× ATR)
- Take profit at 4× ATR
- Use lows for stop checks

## Parameters

```python
DEFAULT_PARAMS = {
    "vidya_fast_period": 6,       # Short effective period for VIDYA
    "vidya_slow_period": 24,      # Long effective period for VIDYA
    "vidya_cmo_period": 9,        # CMO period for efficiency ratio
    "atr_period": 14,
    "atr_percentile_window": 50,
    "atr_percentile": 80,
    "stop_loss_mult": 2.0,
    "take_profit_mult": 4.0,
}
```

## Anti-Pattern Compliance

- ✅ 2 AND conditions (crossover + expansion)
- ✅ Adaptive indicator — but direction-aware (CMO-based, not ER-based)
- ✅ ATR expansion as confirmation
- ✅ No hysteresis, no regime switching
- ✅ Not previously attempted
- ✅ Short lookbacks suitable for 365-day window

## Expected Behavior

- Target 50-200 trades/year on 1h
- Target 20-50 trades/year on 4h (should outperform KAMA's 12 due to CMO direction awareness)
- May outperform KAMA on 4h significantly
- BTC expected to dominate (standard trend-following pattern)
- OOS > IS risk on BTC (recent trending regime)

## Reference

Chande, T. S. (1995). "VIDYA: Variable Index Dynamic Average." *Technical Analysis of Stocks & Commodities*.
ETIA paper (2026): "Ensemble trading indicator analysis for improved market prediction" — Springer, mentions VIDYA + MAMA as adaptive approaches.
