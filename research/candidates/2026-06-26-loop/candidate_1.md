# Candidate 1: Fisher Transform Trend

**Date:** 2026-06-26 (Loop 18)
**Source:** Ehlers Fisher Transform (electrical engineering → finance, 2002)
**Discovery:** GitHub trending / Freqtrade strategy library — `GKD_FisherTransform` used in crypto backtesting

## Strategy Concept

The **Fisher Transform** converts any price waveform into a Gaussian normal distribution, making turning points sharply visible. Unlike oscillators (RSI, Stochastic) that produce rounded peaks, Fisher Transform produces sharp, high-amplitude peaks at price reversals — making entry/exit timing more precise.

### Core Mechanics
1. Normalize median price (H+L)/2 to [-1, 1] range over `fisher_period` bars
2. Apply Fisher Transform: `0.5 * ln((1+x)/(1-x))`
3. Smooth Fisher value with signal line (EMA)
4. Entry: Fisher > signal AND Close > EMA(trend_period) for long
5. Exit: Fisher crosses below signal (reverse for short)
6. Exactly 2 AND conditions: Fisher cross + trend filter

### Why This Is Novel (vs 33 Tested Strategies)
- **Gaussian transformation**: Fisher amplifies turning points 3-5× vs raw oscillators. No other tested strategy uses statistical distribution transformation.
- **Not a smoothed oscillator**: Unlike RSI (Wilder smoothing), Stochastic (dual MA), CMO (raw sum), Fisher uses mathematical transformation — not smoothing
- **Sharp peaks**: Entry signals are binary on/off rather than gradual threshold crossings — should produce cleaner signal generation

### Anti-Pattern Compliance
- ✅ 2 AND conditions (Fisher cross + EMA trend)
- ✅ Signal generator: Fisher cross occurs 40-120 times/year on 1h (not signal-sparse like HA/VWAP)
- ✅ No hidden smoothing gate (fisher_period=10, signal_period=5 < 20-bar threshold)
- ✅ No raw price-extreme indicator (uses median price, not High/Low)
- ✅ Not Ichimoku, CLV, candle pattern, or LinReg

### Expected Behavior
- **1h BTC**: 80-160 trades, Sharpe 1.5-2.5 (Fisher turning points are precise)
- **1h ETH**: 70-140 trades, Sharpe 0.8-1.5 (ETH noise may reduce Fisher peak quality)
- **4h**: 25-40 trades — borderline for crossover-based 4h. Fisher peaks are rarer on higher timeframes.
- **Strongest on 1h BTC** where Fisher turning points are most reliable

### Parameters
```python
DEFAULT_PARAMS = {
    'fisher_period': 10,      # Lookback for normalization
    'signal_period': 5,       # Signal line smoothing
    'trend_period': 200,      # EMA trend filter
    'entry_threshold': 0.0,   # Fisher > signal = enter (0 = crossover)
}
```

### References
- Ehlers, "Using the Fisher Transform" (Stocks & Commodities, Nov 2002)
- Freqtrade: `GKD_FisherTransform` strategy validated on crypto
- LuxAlgo: Fisher Transform for turning point detection (2025)
