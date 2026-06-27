# TRIXTrend — Triple Exponential Average Crossover + Trend Filter

## Source
Jack Hutson (1980s), "TRIX: Triple Exponential Smoothing Oscillator."
Technical Analysis of Stocks & Commodities magazine.

## Hypothesis
TRIX zero-cross detects momentum shifts with less noise than single/double-smoothed oscillators. EMA200 trend filter provides directional bias. 2 conditions. TRIX's triple EMA construction (EMA(EMA(EMA(price)))) is mathematically similar to a low-pass filter — preserves signal frequency better than Wilder-smoothed oscillators (RSI, Stochastic) while filtering high-frequency noise.

## Entry Conditions (exactly 2 AND gates)
1. **TRIX Crossover**: TRIX(period) > TRIX_signal(period) for long / TRIX < TRIX_signal for short
2. **Trend Filter**: Close > EMA(200) for long / Close < EMA(200) for short

## Exit
Reverse TRIX crossover (TRIX < TRIX_signal for long / TRIX > TRIX_signal for short)

## Parameters
- `trix_period`: 14 (standard, balances signal density vs noise reduction)
- `signal_period`: 9 (standard TRIX signal line)
- `trend_period`: 200 (EMA trend filter)
- `min_bars`: 150 (triple EMA needs warmup)

## Expected
- BTC 1h: 100-200 trades, Sharpe 1.5-2.5
- ETH 1h: 80-160 trades, Sharpe 0.5-1.5 (ETH OOS risk per systemic pattern)
- BTC 4h: 20-30 trades, Sharpe 0.5-1.5 (4h crossover scarcity risk)
- ETH 4h: 15-25 trades, Sharpe -0.5-0.5 (likely fails trade count)

## Anti-patterns avoided
- 2 conditions only
- Triple smoothing is mathematical transformation (similar to Fisher), not percentile gate
- No smoothing >20 bars on sub-components (14-period base, not 34 like AO)
- Normalized output (~0-centered) — works across volatility regimes

## Risk: 4h trade scarcity
TRIX crossover on 4h may produce <30 trades (same as all crossover/oscillator 4h strategies across Loops 5-18). This is expected and will not be considered a strategy failure — the 1h results are the primary target.

## Relation to prior work
- CMOTrend (Loop 12): Sum-based momentum, 114 trades on BTC 1h. TRIX is triple-smoothed but preserves crossovers better than CMO's single-smoothing.
- FisherTransformTrend (Loop 18): Mathematical transformation, 296 trades on BTC 1h. TRIX is also transformational (triple EMA) but less aggressive — should generate 100-200 trades.
- MacdAdxTrend (Loop 5): MACD cross + ADX trend, 240-250 trades on 1h. TRIX replaces MACD's single-EMA smoothing with triple-EMA, and EMA200 replaces ADX's smoothed trend gate.
