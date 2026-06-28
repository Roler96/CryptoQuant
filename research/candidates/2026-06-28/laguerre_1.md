# Candidate 1: LaguerreRSIExpansion

**Date:** 2026-06-28
**Source:** ArXiv Monday — derived indicator innovation
**Status:** Candidate

## Strategy Concept

Laguerre RSI + ATR Expansion Confirmation

## Why This Could Work

1. **Laguerre RSI reduces lag vs standard RSI.** Standard RSI uses Wilder's smoothing (EMA with alpha=1/period), introducing 5-8 bar lag. Laguerre RSI uses a 4-pole gamma filter (gamma=0.5) that produces faster responses to trend changes while maintaining smoothness. This means earlier entries during trend transitions without increased noise.

2. **ATR expansion filter is the #1 confirmation.** Proven across Loops 5, 6, 11, and 15 to add ~1.5-2.0 Sharpe points to any normalized oscillator. The ATR > SMA(ATR,50) × 0.8 filter eliminates 60-70% of false oscillator crossovers in low-volatility/choppy conditions.

3. **Fits the proven template: normalized oscillator + ATR expansion.** RSIExpansionTrend (Loop 15) achieved 4/4 main gate pass with Sharpe 4.39/2.94 on BTC. Laguerre RSI's lower lag could produce even earlier entries, potentially improving OOS robustness.

4. **Theoretically addresses Loop 15's RSI limitation.** Standard RSI's lag means it confirms a trend after it's already developed — the same problem identified with ADX on 4h. Laguerre RSI's gamma filter should generate crossover signals 2-4 bars earlier, capturing more of the initial trend move.

## Entry Conditions (2 AND conditions)

1. **LaguerreRSI(14, gamma=0.5) > 50** — directional bias (uptrend)
2. **ATR expansion:** bar_range > rolling_percentile(ATR(14), window=50) at 80th percentile — volatility confirmation

## Exit Conditions

1. LaguerreRSI crosses below 50 — exit on signal reversal

## Risk Management

- Use ATR-based stop loss (2× ATR trailing)
- Take profit at 4× ATR
- Use lows for stop checks (standard crypto backtest convention)

## Parameters

```python
DEFAULT_PARAMS = {
    "lrsia_period": 14,
    "lrsia_gamma": 0.5,
    "atr_period": 14,
    "atr_percentile_window": 50,
    "atr_percentile": 80,
    "stop_loss_mult": 2.0,
    "take_profit_mult": 4.0,
}
```

## Anti-Pattern Compliance

- ✅ 2 AND conditions (not 3+)
- ✅ Normalized oscillator (0-100 Laguerre RSI)
- ✅ ATR expansion as confirmation (strongest single filter)
- ✅ No hysteresis, no regime switching, no hidden AND gates
- ✅ Not previously attempted (verified via patterns.md + file search)
- ✅ Short lookbacks (14-bar) suitable for 365-day window

## Expected Behavior

- Target 50-200 trades/year on 1h
- Target 30-80 trades/year on 4h
- Higher trade count than RSIExpansionTrend due to earlier crossovers
- Potential for OOS > IS if Laguerre filter captures recent trending conditions well
- Risk: earlier entries = higher whipsaw in choppy periods. ATR expansion should mitigate this.

## Reference

Ehlers, J. F. (2002). "The Laguerre RSI." *Technical Analysis of Stocks & Commodities*.
