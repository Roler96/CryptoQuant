# Strategy Candidate: Williams %R Trend (WilliamsRTrend)

**Generated:** 2026-06-27
**Source:** Research synthesis — Williams %R (Larry Williams, 1973), adapted for crypto trend following with EMA200 trend filter

## Strategy Concept

Williams %R is a normalized momentum oscillator (0 to -100) measuring the close position within the High-Low range over N periods. Unlike Stochastic (smoothed %K/%D with a signal line), Williams %R is raw and unfiltered — it reacts faster to price extremes. Combined with an EMA200 trend filter, it creates a 2-condition trend-following entry: %R crosses above -20 (momentum strength) AND price > EMA200 (uptrend) → long; %R crosses below -80 AND price < EMA200 → short. Exit at %R mid-line (-50) crossover. This is a faster alternative to Loop 7's StochRSITrend (which used smoothed stochastic), and the fixed -20/-80 thresholds are inherently normalized — working identically across symbols and timeframes.

## Pseudocode

```
# Indicators
williams_r = williams_r(high, low, close, period=14)   # 0 to -100
ema200 = ema(close, 200)

# Entry (2 conditions)
long_entry = (williams_r crosses_above -20) AND (close > ema200)
short_entry = (williams_r crosses_below -80) AND (close < ema200)

# Exit
long_exit = (williams_r crosses_below -50)
short_exit = (williams_r crosses_above -50)

# Signal: 1=long, -1=short, 0=flat
```

## Expected Indicators

- [x] Williams %R — needs new implementation in signals.py (or inline calculation)
- [x] EMA — already in signals.py

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| wr_period | 10-20 | 14 | Williams %R lookback period |
| wr_overbought | -25 to -15 | -20 | Entry threshold for long |
| wr_oversold | -85 to -75 | -80 | Entry threshold for short |
| wr_mid | -55 to -45 | -50 | Exit threshold (mid-line) |
| trend_period | 150-300 | 200 | EMA trend filter period |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | Normalized oscillator + trend filter = proven template. StochRSITrend achieved Sharpe 2.35 on BTC 1h. %R is faster — expect similar or slightly higher |
| MaxDD | <40% | <30% | Trend filter caps drawdowns. Mid-line exit (-50) prevents holding through reversals |
| Win Rate | >35% | >45% | Williams %R is reactive — more trades but lower win rate than Stochastic. 35-45% is typical for trend-following oscillators |

## References

- [Williams %R Strategy — QuantifiedStrategies.com (81% Win Rate)](https://www.quantifiedstrategies.com/williams-r-strategy/)
- [Williams %R Strategy (TradingView) — 135 Backtests](https://tradesearcher.ai/strategies/1969-williams-r-strategy)
- [Williams %R 2026 Guide — TakeProfitApp (54.3% WR)](https://takeprofitapp.com/en/learn/williams-percent-r-trading)

## Implementation Notes

- Signal convention: 1=long, -1=short, 0=flat
- Williams %R calculation: %R = (highest_high(N) - close) / (highest_high(N) - lowest_low(N)) * -100
- Entry signal: %R crosses above -20 → momentum breakout (going with trend, not fading)
- This is a TREND-FOLLOWING strategy, not mean-reversion — we enter on strength, not weakness
- Add `williams_r()` function to `cryptoquant/strategy/signals.py`
