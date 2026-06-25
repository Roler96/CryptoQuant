# Candidate 1: Parabolic SAR Trend Following

**Date:** 2026-06-26
**Source:** Classic TA literature + je-suis-tm/quant-trading GitHub
**Family:** Trend Following (SAR-based)

## Hypothesis
Parabolic SAR acts as a dynamic stop-and-reverse indicator. When price crosses above PSAR, it signals a trend reversal to bullish. Combined with a simple trend filter (EMA200), this provides a clean 2-condition entry that should generate 50-150 trades/year on 1h data.

## Why This Should Work
- PSAR is fundamentally different from oscillators (Stochastic/Aroon) and breakouts (channel/BB) — it's acceleration-based
- PSAR naturally follows trend acceleration, meaning entries occur during genuine trend development, not late
- EMA200 trend filter eliminates counter-trend PSAR crosses (which are notoriously unreliable)
- 2 total conditions: PSAR cross + trend filter
- No complex exit — just PSAR reverse cross

## Strategy Design
```
Entry (Long):  price > PSAR AND close > EMA200
Exit (Long):   price < PSAR  
Entry (Short): price < PSAR AND close < EMA200
Exit (Short):  price > PSAR
```

## Parameters
- `psar_af_start=0.02` — standard acceleration factor start
- `psar_af_step=0.02` — standard step
- `psar_af_max=0.20` — standard max
- `trend_period=200` — EMA200 for trend filter

## Expected Performance
- **Trades:** 50-150/year (PSAR generates frequent crosses)
- **Sharpe target:** >1.0 on BTC 1h
- **Win rate:** 40-50% typical for TF strategies
- **Risk:** PSAR whipsaw in ranging markets (mitigated by trend filter)

## Anti-Pattern Check
- ✅ ≤2 AND conditions (PSAR cross + trend filter)
- ✅ Not a candle pattern / CLV / volume percentile
- ✅ Not momentum oscillator on ETH 1h
- ✅ Different from all 21 previous strategies
- ✅ Price-action based entry (not pattern recognition)
- ⚠️ May underperform on 4h (fewer PSAR crosses) — focus on 1h

## Baseline
Similar to EMA cross systems but with adaptive acceleration — should generate earlier entries than fixed-period moving averages.
