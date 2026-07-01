# Candidate 4: Bollinger Band Breakout with Volume Confirmation

**Date:** 2026-06-25
**Source:** Literature review — Bollinger Band breakout strategies (arxiv, TradingView, QuantConnect)
**Confidence:** Medium-High

## Strategy: BBandBreakoutVolume

### Concept
Bollinger Band breakouts signal volatility expansion and potential trend initiation. Adding a volume filter confirms institutional participation. Unlike the EMA crossover approach (Loop 1), this is a *volatility-based* entry — it fires when price exceeds the volatility envelope, not when short-term trend crosses long-term trend.

### Entry Rules (exactly 2 conditions)
- **Long:** close > BB_upper(20, 2.0) AND volume > SMA(volume, 20)
- **Short:** close < BB_lower(20, 2.0) AND volume > SMA(volume, 20)

### Exit Rules
- **Long exit:** close < BB_middle (SMA 20) OR trailing stop at 2× ATR(14)
- **Short exit:** close > BB_middle (SMA 20) OR trailing stop at 2× ATR(14)

### Why it avoids anti-patterns
- ✅ Exactly 2 AND conditions (not 4+)
- ✅ Short lookbacks: BB=20, volume SMA=20, ATR=14 (all ≤168)
- ✅ Trend-following, not mean reversion
- ✅ No hysteresis on primary signal
- ✅ Volume filter is secondary, not a gate on a rare event
- ✅ BB upper/lower touch is a frequent event — should produce 50-200 trades/year

### Expected behavior
- BTC 1h: 80-150 trades/year, Sharpe > 1.0 expected
- 4h timeframes: fewer trades (~30-60) but higher quality
- ETH likely mirrors BTC with slightly lower Sharpe

### Different from past strategies
- EMACrossATRFilter: trend crossover + volatility filter
- BBandBreakoutVolume: volatility breakout + volume confirmation (orthogonal entry logic)
