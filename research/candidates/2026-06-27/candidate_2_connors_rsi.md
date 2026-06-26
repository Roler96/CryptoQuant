# Candidate: ConnorsRSITrend

**Date:** 2026-06-27 (Saturday — QuantConnect/Medium blog discovery)
**Source:** Connors Research — Larry Connors' composite RSI indicator, adapted for crypto trend following

## Strategy Summary

Connors RSI (CRSI) composite oscillator > 70 threshold + EMA200 trend filter.

## Indicator Definition

Connors RSI = [RSI(3) + RSI(Streak, 2) + PercentRank(ROC(close), 100)] / 3

- **RSI(3):** Ultra-short Wilder RSI — captures immediate overbought/oversold
- **RSI(Streak, 2):** RSI applied to consecutive up/down close streak length — trend persistence
- **PercentRank(ROC, 100):** Where current 1-bar rate-of-change ranks in last 100 bars — momentum percentile

This is a single composite indicator (3 sub-components combined into one 0-100 value), NOT 3 independent entry conditions. The entry uses a single threshold on the composite.

## Entry Conditions (Exactly 2)

1. **CRSI threshold:** CRSI > 70 for long, CRSI < 30 for short
2. **EMA200 trend filter:** Close > EMA200 for long, Close < EMA200 for short

## Exit Conditions

- Exit long when CRSI crosses below 50 (momentum neutral)
- Exit short when CRSI crosses above 50

## Why This Should Work

- Composite indicator aggregates 3 momentum dimensions into 1 signal — higher signal-to-noise than single-dimensional oscillators
- Normalized 0-100 scale → should work across timeframes
- RSI(3) is ultra-fast (near-zero lag) — avoids the smoothing-lag problem on ETH
- Streak RSI captures trend persistence — filters out one-off noise bars
- PercentRank normalizes across volatility regimes — self-scaling like BB %B
- Exactly 2 AND conditions (composite threshold + trend) ✓
- Follows Fisher Transform pattern: internal computation → single threshold output

## Anti-Pattern Check

- ✅ 2 conditions (not ≥3) — the 3 sub-components are internal to the indicator, not explicit entry gates
- ✅ Normalized 0-100 indicator (good for 4h)
- ✅ Fixed threshold, not crossover
- ✅ Close-based, not price-extreme based (OK for ETH)
- ✅ No hidden smoothing gate — RSI(3) has ~5-bar effective lag, well under 20
- ⚠️ Streak RSI on ETH may be noisy — ETH's wick microstructure could produce false streak signals
- ⚠️ Unknown 4h trade count — composite may be slower than single oscillators

## Predicted Performance

- BTC 1h: Sharpe ~1.5-2.5, ~100-200 trades
- BTC 4h: Sharpe ~0.8-1.5, ~30-50 trades (threshold-based, should clear gate)
- ETH 1h: Sharpe ~0.5-1.5 (CRSI may filter ETH noise better than raw indicators)
- ETH 4h: Likely OOS failure (ETH 4h pattern) but may pass main gate

## Risk Factors

- Composite computation is heavier than simple oscillators (3 Numba-friendly operations)
- Ultra-short RSI(3) may produce excessive whipsaw on 1h if threshold is too loose
- PercentRank lookback of 100 bars → first 100 bars of backtest have no valid CRSI (handled by min_bars=150)
- CRSI may be too complex → interpretability of failures is harder than single-indicator strategies
