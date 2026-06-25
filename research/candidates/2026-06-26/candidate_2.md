# Candidate 2: Ichimoku Cloud Breakout

**Date:** 2026-06-26
**Source:** dagzk/Ichimoku_Backtest (GitHub) + classic Japanese TA
**Family:** Trend Following (Cloud-based)

## Hypothesis
The Ichimoku Kinko Hyo system's Tenkan-sen (9) / Kijun-sen (26) crossover generates timely entry signals, while the Kumo (cloud) provides a robust trend filter. A 2-condition entry (TK cross + price above cloud) should produce 80-200 trades/year with positive expectancy on crypto 1h.

## Why This Should Work
- Tenkan/Kijun cross is a fast-responsive moving average pair — catches trends earlier than EMA12/26
- The Kumo (Senkou Span A/B projected 26 bars forward) is a forward-looking support/resistance zone — not just a lagging trend indicator
- Ichimoku is battle-tested across decades of Japanese trading and multiple asset classes
- 2 total conditions: TK cross + cloud position
- Different from all 21 strategies tested — no cloud/forward-looking filter used before

## Strategy Design
```
Entry (Long):  Tenkan-sen crosses ABOVE Kijun-sen AND close > Senkou Span A AND close > Senkou Span B
Exit (Long):   Tenkan-sen crosses BELOW Kijun-sen
Entry (Short): Tenkan-sen crosses BELOW Kijun-sen AND close < Senkou Span A AND close < Senkou Span B
Exit (Short):  Tenkan-sen crosses ABOVE Kijun-sen
```

## Parameters
- `tenkan_period=9` — standard Tenkan-sen (conversion line)
- `kijun_period=26` — standard Kijun-sen (base line)
- `senkou_b_period=52` — standard Senkou Span B
- `displacement=26` — standard cloud displacement

## Expected Performance
- **Trades:** 80-200/year (TK crosses frequently on 1h)
- **Sharpe target:** >1.0 on BTC 1h
- **Win rate:** 42-48% typical
- **Risk:** Cloud false positives in low-volatility consolidation (mitigated by requiring both cloud spans)

## Anti-Pattern Check
- ✅ ≤2 AND conditions (TK cross + cloud filter)
- ✅ Not a candle pattern / CLV / volume percentile
- ✅ Not momentum oscillator on ETH 1h (TK is a MA crossover, not an oscillator)
- ✅ Different from all 21 previous strategies
- ✅ Price-action based entry
- ⚠️ May have too few signals on 4h (2190 bars vs 8760 at 1h) — focus on 1h
- ⚠️ ETH 1h may show OOS degradation (systemic pattern in loops 4-8) — test cautiously

## Baseline
Should outperform plain EMA crossover (Loop 1's EMACrossATRFilter) because the entry trigger is more responsive (9/26 vs 12/26) and the trend filter is forward-looking (cloud vs backward-looking EMA).
