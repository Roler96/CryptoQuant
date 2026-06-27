# Candidate 1: Z-Score Momentum Trend (ZScoreTrend)

**Date:** 2026-06-27
**Source:** Adapted from "Systematic Crypto Trading Strategies" (Medium, Brian Plotnik, Jun 2025)
**Status:** Proposed

## Strategy Concept

Z-score normalized momentum oscillator with EMA200 trend filter. The Z-score normalizes returns by their rolling standard deviation, making the signal adaptive to changing volatility regimes without parameter switching.

## Entry Logic (2 conditions)

1. **Z-score cross:** Z-score(short=20, long=100) crosses above 0 → long signal; crosses below 0 → short signal
2. **Trend filter:** Close > EMA(200) for long; Close < EMA(200) for short

Z-score formula:
```
z_score = (rolling_mean(returns, 20) - rolling_mean(returns, 100)) / rolling_std(returns, 100)
```

## Exit Logic
- Z-score crosses back through 0 (reverse signal)
- Trailing stop at 2× ATR(14)

## Why This Should Work
- Normalized by definition (Z-score is always mean-0, std-1 in theory) — should work across timeframes without per-combo tuning
- Not previously tested: RiskAdjustedMomentum (Loop 8) used return/vol ratio, not Z-score
- 2 total AND conditions — conforms to proven template (82% pass rate across 148 combos)
- Short lookback (20/100) avoids >20-bar smoothing lag anti-pattern (Loop 13's AO failure)

## Anti-Patterns Avoided
- ✅ 2 conditions (not ≥3)
- ✅ No hidden smoothing gate (20-bar Z-score period = 1 effective condition, not hidden AND)
- ✅ Normalized indicator (works across BTC/ETH/timeframes like %B, Stochastic, CCI)
- ✅ Not raw price-extreme (safe for ETH)
- ✅ Entry trigger not signal-sparse (should generate 80-200 trades/year)

## Parameters
```
zscore_short = 20
zscore_long = 100
trend_period = 200
atr_period = 14
trailing_mult = 2.0
```

## Expected Backtest Combos
- BTC/USDT 1h, BTC/USDT 4h, ETH/USDT 1h, ETH/USDT 4h
- Target: 50-200 trades, Sharpe 1.0-2.5
