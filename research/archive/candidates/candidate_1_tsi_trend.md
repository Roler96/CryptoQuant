# Candidate 1: TSI Trend (True Strength Index Zero-Cross + EMA200)

**Loop:** 14
**Date:** 2026-06-28
**Source:** Free search (Sunday) — QuantifiedStrategies.com TSI backtest literature

## Concept

The **True Strength Index (TSI)** is a double-smoothed momentum oscillator developed by William Blau. Unlike RSI (single-smoothed) or Stochastic (positional), TSI applies two rounds of EMA smoothing:

```
TSI = 100 × EMA(EMA(Δprice, long), short) / EMA(EMA(|Δprice|, long), short)
```

Typical params: long=25, short=13 (Blau's defaults). Range: -100 to +100. Zero-cross signals momentum regime change with minimal whiplash due to double-smoothing.

## Entry Conditions (2 total)

1. **TSI zero-cross:** TSI(25,13) crosses above 0 → bullish momentum regime
2. **EMA200 trend filter:** Close > EMA(200) → only trade in uptrend

## Exit

TSI crosses below 0 → exit long

## Why This Should Work

- **Double-smoothing reduces whiplash** — TSI produces fewer false signals than RSI or Stochastic, maintaining trade count in the 50-200 sweet spot
- **Normalized range (-100 to +100)** — zero-cross threshold works identically on BTC/ETH × 1h/4h without per-combo tuning
- **Proven in equity literature** — QuantifiedStrategies documents TSI as effective for trend identification with Sharpe > 1.0 in equity backtests
- **2 conditions exactly** — satisfies the proven template (TSI cross + trend filter)
- **Not ADX/MACD/oscillator family** — avoids the known 4h trade-scarcity problem since TSI is inherently less smoothed than ADX

## Anti-Pattern Check

- ✅ Not mean reversion (with EMA200 trend filter)
- ✅ Not ≥3 AND conditions (2 conditions)
- ✅ Not candle-pattern based (oscillator-based, mechanical)
- ✅ Not CLV-based
- ✅ Not Ichimoku
- ✅ Volume-independent (avoids volume filter gate problems)

## Parameters

| Param | Value | Rationale |
|-------|-------|-----------|
| `tsi_long` | 25 | Blau's default — long-term smoothing |
| `tsi_short` | 13 | Blau's default — signal smoothing |
| `trend_period` | 200 | Standard EMA trend filter |
| `min_bars` | 200 | Allow TSI to stabilize |

## Expected Trade Count

- 1h: 80-150 trades/year
- 4h: 25-45 trades/year (may be tight on 4h due to double-smoothing)

## Risk

4h trade count may fall below 30 if double-smoothing compounds 4h bar scarcity (similar to KAMA/PFE on 4h). Ready to adjust `tsi_long` to 13 for 4h if needed.
