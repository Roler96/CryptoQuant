# Strategy Candidate: RmiTrend

**Generated:** 2026-06-28
**Source:** Quantitative Finance Literature — Relative Momentum Index (RMI), Roger Altman 1993

## Strategy Concept

RMI (Relative Momentum Index) is a variation of RSI that uses momentum (price change over N bars) instead of raw daily price changes. This provides additional smoothing and clearer turning points compared to standard RSI. The RMI crossover of its signal line generates trend-following entries. Combined with EMA200 trend filter for directional confirmation = exactly 2 conditions. RMI improves on RSI by measuring sustained momentum rather than single-bar price changes, reducing false signals in choppy markets. Unlike Stochastic (which measures position within a range), RMI measures the strength of directional movement over a configurable momentum period.

## Pseudocode

```
1. Compute momentum: mom = close - close.shift(momentum_period)
2. Separate up/down momentum:
   - up = max(mom, 0)
   - down = abs(min(mom, 0))
3. Smooth with Wilder's EMA (rmi_period):
   - avg_up = EMA(up, rmi_period)
   - avg_down = EMA(down, rmi_period)
4. RMI = 100 - 100 / (1 + avg_up / max(avg_down, ε))
5. Signal = EMA(RMI, signal_period)
6. ENTRY: RMI crosses above Signal AND close > EMA200 → LONG=1
7. ENTRY: RMI crosses below Signal AND close < EMA200 → SHORT=-1
8. EXIT: RMI crosses back below/above Signal (reverse signal)
```

## Expected Indicators

- [x] EMA — already in signals.py
- [ ] RMI (Relative Momentum Index) — need to add to cryptoquant/strategy/signals.py

## Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| momentum_period | 3-10 | 5 | Bars for momentum calculation |
| rmi_period | 10-20 | 14 | Wilder's EMA period for smoothing |
| signal_period | 5-15 | 9 | Signal line EMA period |
| trend_period | 100-300 | 200 | EMA period for trend direction filter |

## Test Pairs & Timeframes

- Pairs: BTC/USDT, ETH/USDT
- Timeframes: 1h, 4h

## Expected Performance Range

| Metric | Min | Target | Reason |
|--------|-----|--------|--------|
| Sharpe | >0.3 | >0.5 | RMI reduces RSI noise by filtering through momentum; 2-condition template has 80% pass rate |
| MaxDD | <40% | <30% | Wilder smoothing provides stable oscillator values |
| Win Rate | >35% | >45% | Momentum-based entry should filter out pure noise signals |

## References

- [Relative Momentum Index (RMI) — Technical Analysis](https://www.investopedia.com/terms/r/relativemomentumindex.asp)
- [RMI vs RSI — Comparative Analysis](https://www.quantconnect.com/learning/articles/relative-momentum-index)

## Implementation Notes

- RMI is essentially RSI applied to momentum instead of price change
- Wilder's EMA: alpha = 1/period (not 2/(period+1) like standard EMA)
- epsilon for division by zero = 1e-10
- Easy to implement — add rmi() function to cryptoquant/strategy/signals.py
- min_bars = max(momentum_period + rmi_period + signal_period + 10, 50)
- Signal convention: 1=long, -1=short, 0=flat
- Use DEFAULT_PARAMS dict, never hardcode
