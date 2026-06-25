# Candidate 5: Price Channel Breakout with RSI Momentum Confirmation

**Date:** 2026-06-25
**Source:** Literature review — Donchian Channel + RSI filter (QuantConnect, TradingView, "MatFinProtocol Leaderboard")
**Confidence:** Medium

## Strategy: ChannelBreakoutRSI

### Concept
A Donchian-style price channel breakout confirmed by RSI momentum. Breaking the N-period high signals bullish intent, but requiring RSI > 50 filters out false breakouts where price makes a marginal new high without momentum. This is a *price-structure* based entry — different from both EMA crossover and BB breakout.

### Entry Rules (exactly 2 conditions)
- **Long:** close > highest(high, 30) AND RSI(14) > 50
- **Short:** close < lowest(low, 30) AND RSI(14) < 50

### Exit Rules
- **Long exit:** close < SMA(close, 20) OR trailing stop at 2× ATR(14)
- **Short exit:** close > SMA(close, 20) OR trailing stop at 2× ATR(14)

### Why it avoids anti-patterns
- ✅ Exactly 2 AND conditions
- ✅ Short lookbacks: channel=30, RSI=14, SMA=20, ATR=14
- ✅ Trend-following, not mean reversion
- ✅ No hysteresis on primary signal
- ✅ RSI > 50 is a weak filter (fires ~50% of the time) — the channel breakout is the real gate
- ✅ Price channel breakout is a different mechanism from EMA cross and BB breakout

### Key difference from DonchianEnsemble (failed Loop 1)
DonchianEnsemble used 7 channels with binomial voting — too sparse (5 trades/year). This uses a **single** channel (30 bars) with RSI momentum confirmation. The single-channel approach produces many more signals.

### Expected behavior
- BTC 1h: 60-120 trades/year, Sharpe > 1.0
- 4h: 25-50 trades/year (borderline for gate)
- RSI > 50 filter is intentionally loose — it's a momentum direction check, not a precision gate

### Different from past strategies
- EMACrossATRFilter: trend crossover (mathematical curve intersection)
- BBandBreakoutVolume: volatility envelope breakout
- ChannelBreakoutRSI: price structure breakout (absolute price level comparison)
