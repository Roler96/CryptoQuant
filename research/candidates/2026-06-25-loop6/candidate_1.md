# Candidate 1: Close-Location Momentum (clv_atr_momentum)

**Source:** arXiv 2602.00776 "Explainable Patterns in Cryptocurrency Microstructure" — order flow imbalance and VWAP-to-mid deviations are the strongest predictors of short-horizon returns. CLV (Close Location Value) is an OHLCV proxy for intra-bar order flow pressure.

**Date:** 2026-06-25
**Loop:** 6

## Strategy Concept

CLV measures where the close landed within the bar's range:
```
CLV = (close - low) / (high - low)   # 0 = closed at low, 1 = closed at high
```

High CLV (>0.80) + expanding range → strong bullish order flow throughout the bar.
Low CLV (<0.20) + expanding range → strong bearish order flow throughout the bar.

## Entry Conditions (2 conditions)

**Long:** `CLV > 0.80` AND `bar_range > ATR(14) * 1.3`
**Short:** `CLV < 0.20` AND `bar_range > ATR(14) * 1.3`

## Exit

Trailing stop at `2.0 * ATR(14)` from entry price.

## Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| clv_long_threshold | 0.80 | Top quintile of CLV distribution |
| clv_short_threshold | 0.20 | Bottom quintile of CLV distribution |
| atr_period | 14 | Standard lookback |
| expansion_mult | 1.3 | Moderate expansion; higher than 1.0 to filter noise but lower than 1.5 to keep trade count healthy |
| trailing_stop_mult | 2.0 | Proven across all successful strategies |
| min_bars | 30 | Short; CLV is per-bar so signal generation is frequent |

## Expected Trade Count

~100-200 trades/year on 1h (CLV + ATR expansion fires every ~15-30 bars in volatile crypto).
~30-60 trades/year on 4h.

## Why This Should Work

1. **Microstructure backing:** The University of Warsaw paper shows order flow imbalance is the #1 predictor of short-horizon returns. CLV is the best OHLCV proxy for this.
2. **ATR expansion filter:** Proven across all 5 loops as the strongest single confirmation gate (Sharpe 3.19 with RangeExpansionBreakout). Combining novel signal + proven filter.
3. **2 conditions only:** Simple, no AND-gates, no hysteresis, no regime switching.
4. **Short lookback:** ATR(14) is fast enough for 365-day window.
5. **Different from all previous strategies:** No moving average crossovers, no breakout channels, no RSI, no ADX, no MACD.

## Anti-Pattern Check

- ❌ Pure mean reversion? No — this is momentum/continuation (CLV extreme = strong directional pressure).
- ❌ Signal-sparse? No — CLV fires frequently.
- ❌ >2 conditions? No — exactly 2.
- ❌ Long lookbacks? No — ATR(14).
- ❌ Volume percentile gate? No — uses ATR expansion, not volume.
- ❌ Regime switching / hysteresis? No.
- ❌ Momentum-only with no filter? No — has ATR expansion filter.
