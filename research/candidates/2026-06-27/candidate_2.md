# Z-Score Rolling Momentum + EMA200 Trend (ZScoreMomentumTrend)

**Source:** Brian Plotnik Medium article "Systematic Crypto Trading Strategies" (Jun 23, 2025)
**Inspired by:** RiskAdjustedMomentum (Loop 8, 2/4 pass) + Z-score normalization from statistical arbitrage literature
**Date:** 2026-06-27

## Strategy Concept

Rolling Z-score of price returns: (short_MA(returns) - long_MA(returns)) / long_std(returns). 
Enter when Z-score crosses above +1.0 (bullish momentum) or below -1.0 (bearish momentum). 
Filtered by EMA200 trend direction.

## Why This Should Work

- **RiskAdjustedMomentum** (Loop 8, BTC 1h Sharpe=1.68, OOS=2.49) used return/vol ratio — similar concept but with ratio normalization
- Z-score normalization (standard deviation denominator) is scale-invariant across volatility regimes, unlike raw ratio
- The Z-score measures how many standard deviations current short-term return is from the long-term mean — statistically robust
- Short window captures immediate momentum shift; long window + std provides regime-adaptive baseline
- EMA200 trend filter prevents counter-trend entries in strong directional moves

## How It Differs from RiskAdjustedMomentum (Loop 8)
| Component | RiskAdjustedMomentum | ZScoreMomentumTrend |
|-----------|---------------------|---------------------|
| Momentum | 63-bar return | 10-bar MA(returns) |
| Baseline | 20-bar annualized vol | 50-bar MA(returns) + 50-bar std(returns) |
| Normalization | return / vol (ratio) | (short - long) / long_std (Z-score) |
| Entry condition | signal > 0.5 threshold | zscore crosses ±1.0 |
| 4h viability | 20 trades (failed) | Shorter windows (10/50) — potentially more signals |

## Entry Conditions (2 total)
1. **Z-score crossover:** zscore > 1.0 for long, zscore < -1.0 for short
2. **EMA200 trend filter:** close > EMA(200) for long bias, close < EMA(200) for short bias

## Exit
- Z-score crosses back through 0 (momentum neutralized)
- Uses next-bar-open entry (no lookahead)

## Parameters
- `short_period=10` — short MA of log returns (10 bars)
- `long_period=50` — long MA + std of log returns (50 bars)  
- `entry_threshold=1.0` — Z-score > 1.0 long, < -1.0 short
- `exit_threshold=0.0` — Z-score crosses zero = exit
- `trend_period=200` — EMA200 trend filter
- `min_bars=250` — warmup: 200+50 bars

## Expected Trade Count
- 1h: ~80-180 trades (10/50 windows = 2-4 days of context, frequent crossovers)
- 4h: ~25-50 trades (shorter windows than RiskAdjustedMomentum's 63-bar)

## Known Risks
- Z-score ±1.0 threshold: ~68% of values fall within ±1σ under normality — reasonable signal density
- 4h: 50-bar long window = 200 hours (8.3 days) — signal updates are slow. Trade count may be marginal (<30).
- ETH: Z-score is based on returns, not bar extremes — should be less vulnerable to ETH noise than Elder Ray/Aroon
- Parameter sensitivity: 10/50 windows are a starting point; optimization may be needed

## Anti-Pattern Check
- ✅ 2 AND conditions (Z-score threshold + EMA200 trend)
- ✅ Not a raw price-extreme indicator (returns-based)
- ✅ Not triple-smoothed (simple MA of returns)
- ✅ Not candle pattern detection
- ✅ Returns-based = ETH-robust (close-based, not extreme-based)
- ⚠️ 4h: 50-bar window may cause trade scarcity (known anti-pattern)
