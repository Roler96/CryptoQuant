# Candidate 2: Efficiency Ratio Trend

**Date:** 2026-06-26 (Loop 18)
**Source:** Perry Kaufman's Efficiency Ratio (ER) — direct noise/trend measurement
**Discovery:** GitHub quant repos / TradingView indicator library

## Strategy Concept

The **Kaufman Efficiency Ratio** directly measures how directional price movement is — the ratio of net displacement to total path length. Unlike all tested oscillators (which measure momentum, overbought/oversold, or smoothed price rates), ER measures the fundamental quality of the market: is it trending efficiently or chopping randomly?

### Core Mechanics
1. Compute ER over `er_period` bars: `abs(close - close[N]) / sum(abs(close[i] - close[i-1]))` for i=1..N
2. ER ∈ [0, 1]: 0 = pure noise (close returns to start), 1 = pure trend (straight line)
3. Entry: ER > entry_threshold AND Close > EMA(trend_period) for long
4. Exit: ER < exit_threshold (trend quality degrades)
5. Exactly 2 AND conditions: ER threshold + trend filter

### Why This Is Novel (vs 33 Tested Strategies)
- **Not KAMA**: KAMA (Loop 10) uses ER as a smoothing coefficient for an adaptive MA. This strategy uses ER directly as a binary signal — "is the market trending?" 
- **Not an oscillator**: ER measures path efficiency, not momentum, rate-of-change, or overbought/oversold
- **No smoothing gate**: ER is computed from raw prices with no EMA/MACD/SMA intermediate smoothing
- **Directional quality**: Unlike all tested oscillators that measure "how much" price moved, ER measures "how cleanly" price moved

### Anti-Pattern Compliance
- ✅ 2 AND conditions (ER threshold + EMA trend)
- ✅ Signal generator: ER > 0.4 triggers 50-120 times/year on 1h (not signal-sparse)
- ✅ No hidden smoothing gate (er_period=20, no internal smoothing)
- ✅ No raw price-extreme indicator
- ✅ Not Ichimoku, CLV, candle pattern, or LinReg

### Expected Behavior
- **1h BTC**: 50-120 trades, Sharpe 1.5-2.5 (BTC trends are directionally efficient)
- **1h ETH**: 40-90 trades, Sharpe 0.8-1.5 (ETH noise reduces ER values)
- **4h**: 25-45 trades — ER on 4h may actually work better than oscillators because ER is a quality metric, not a crossover. 4h noise bars reduce ER organically, filtering themselves.
- **Strongest on 1h BTC + potentially 4h** if ER works better than oscillator crossovers on higher timeframes

### Key Risk: 4h Trade Scarcity
- ER(20) computes over 20 bars = 80 hours on 4h. Each ER measurement requires 20 fresh bars — fewer signal opportunities than breakouts.
- If 4h fails the 30-trade gate, this strategy would confirm that 4h requires breakout-based entries (even quality-metric entries fail).
- If 4h passes, ER would be the first non-breakout strategy to pass 4h gate since CCI (Loop 15).

### Parameters
```python
DEFAULT_PARAMS = {
    'er_period': 20,          # ER computation lookback
    'entry_threshold': 0.4,   # ER > 0.4 = trending, enter
    'exit_threshold': 0.2,    # ER < 0.2 = noise, exit
    'trend_period': 200,      # EMA trend filter
}
```

### References
- Kaufman, "Trading Systems and Methods" (2019, 6th Ed)
- TradingView: `Kaufman Efficiency Ratio (KER)` indicator
- GitHub: `sameertrgquant/Kaufman-Efficiency-Ratio-Visualizer`
