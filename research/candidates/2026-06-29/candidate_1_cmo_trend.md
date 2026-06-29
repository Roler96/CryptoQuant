# Candidate 1: Chande Momentum Oscillator (CMO) Trend

**Date:** 2026-06-29
**Source:** arxiv-inspired — CMO is a classic momentum indicator never tested standalone in this project (only used as VIDYA adaptation metric in Loop 35, which failed on 4h due to adaptive lag, not CMO signal quality).

## Strategy Concept

**CMOTrend** — Uses Chande Momentum Oscillator as a directional entry trigger with EMA200 trend filter.

### Entry Signal
- **Long:** CMO(20) crosses above 0 AND close > EMA(200)
- **Short:** CMO(20) crosses below 0 AND close < EMA(200)
- **Exit:** CMO crosses back to zero (zero-cross reversal)

### Key Ingredients
1. **CMO (Chande Momentum Oscillator):** `100 × (sum_up - sum_down) / (sum_up + sum_down)` — uses raw momentum sums, not Wilder smoothing like RSI. More responsive to sustained directional moves while ignoring single-bar noise (the sum over 20 bars provides natural noise filtering).
2. **EMA200 trend filter** — prevents counter-trend entries in strong bull/bear markets.
3. **Total: 2 conditions** — obeys the 2-condition rule.

### Why This Could Work
- CMO is a sum-based oscillator — distinct from RSI's avg gain/loss ratio. The numerator measures cumulative directional bias, not ratio of averages.
- Unlike Laguerre RSI (which amplifies noise by removing lag), CMO preserves noise rejection through the rolling sum — 20-bar aggregation naturally filters whipsaw.
- CMO values in [-100, 100] provide a clean zero-cross signal (no arbitrary overbought/oversold thresholds).
- Fits the "oscillator + trend filter" template that produced the top strategies (RSIExpansionTrend Sharpe=4.39, StochRSITrend Sharpe=2.35).

### Anti-Pattern Compliance
- ✅ 2 conditions (no hidden AND gates)
- ✅ Not an adaptive indicator (fixed period=20)
- ✅ Standard smoothing via rolling sum (not low-lag)
- ✅ 1h timeframe avoids 4h crossover scarcity
- ✅ Not candle pattern / CLV / volume percentile based

## Parameters
```python
DEFAULT_PARAMS = {
    "cmo_period": 20,
    "trend_period": 200,
}
```

## Expected Performance
- Target: 50-150 trades/year on 1h
- Expected Sharpe: 1.0-2.5 (oscillator + trend filter template)
- BTC should outperform ETH (consistent with oscillator family)
- 4h likely insufficient trades (crossover-based), but include for completeness

## Backtest Combinations
1. BTC/USDT 1h
2. BTC/USDT 4h
3. ETH/USDT 1h
4. ETH/USDT 4h
