# Candidate: ElderRayTrend

**Discovered:** 2026-06-27
**Source:** Quant blog synthesis — Dr. Alexander Elder's Bull/Bear Power + trend filter
**Loop:** 13

## Hypothesis

Elder Ray measures buying/selling pressure as the distance between price extremes (high/low) and a
short-term EMA(13). When Bull Power > 0, buyers are pushing price above the EMA's fair value.
This measures *aggression* — not just trend existence. Combined with EMA200 as trend direction filter,
this should capture entries during strong trending periods when buyers/sellers are most aggressive.

## Entry Logic (2 conditions)

1. **Bull/Bear Power crossover**: Bull Power crosses above 0 (long) or Bear Power crosses below 0 (short)
   - Bull Power = High - EMA(13)
   - Bear Power = Low - EMA(13)
   - Cross above 0 = price extremes break above short-term fair value
2. **EMA200 trend filter**: Close > EMA(200) for longs, Close < EMA(200) for shorts

## Exit Logic

- Reverse signal (opposite power crossover)
- Or trail based on opposite power crossing

## Rationale

- Elder Ray is a classic indicator (Dr. Elder, 1989) — time-tested concept
- Measures buying/selling *aggression*, not just direction
- 2 conditions, no hidden AND gates
- Should generate 100-300 trades on 1h (frequent crossovers)
- Unlike RSI/Stochastic which normalize, Elder Ray is unbounded — trend-strength proportional

## Anti-Pattern Check

- ✅ 2 conditions (not ≥3)
- ✅ Not CLV-based (uses high/low, not close position within range)
- ✅ Not candle pattern-based
- ✅ Not Ichimoku
- ✅ Not ADX-dependent
- ✅ Uses proven EMA200 trend filter (worked in Loops 1, 7, 9, 10, 11)
- ⚠️ Bull Power > 0 is a very frequent condition — may generate excessive signals on 1h
- ⚠️ Signal quality may be diluted (need to verify win rate > 35%)
- ⚠️ 4h: expected 30-60 trades (marginal for gate)

## Expected Trade Count

- BTC 1h: 150-300
- ETH 1h: 150-350
- BTC 4h: 35-60
- ETH 4h: 30-50

## Parameters (initial)

```python
DEFAULT_PARAMS = {
    "er_period": 13,        # Elder Ray EMA period (standard Elder setting)
    "trend_period": 200,    # Trend filter EMA period
}
```

## Next Steps

1. Implement in `research/backtest_elder_ray_trend.py`
2. Test with `tests/research/test_backtest_elder_ray_trend.py`
3. Backtest: BTC/ETH × 1h/4h × 365d
