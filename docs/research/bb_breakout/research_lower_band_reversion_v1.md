# BB Lower Band Mean Reversion — Strategy Failure v1

> **One-line summary:** BB Lower Band mean reversion on 1h BTC fails decisively (Sharpe -0.87 baseline, -0.43 filtered). Best optimized configuration achieves Sharpe +0.26 with only 4/7 walk-forward profitable. Mean reversion does not work on 1h crypto — consistent with prior RSI(2) mean-reversion failure (Sharpe -3.57).

## Hypothesis

The BB Upper Breakout strategy (momentum/continuation) works well in trending markets (Sharpe +1.38, 6/7 WF). This research tested the complementary strategy: buying when price touches the lower Bollinger Band and bounces — a mean-reversion signal that should work best in ranging/sideways markets where momentum strategies struggle.

**Hypothesis:** Lower BB touches in non-crash conditions produce small but reliable bounces (+1-3%) back toward the mean. This is a classic mean-reversion signal that should complement the momentum-based Upper Breakout strategy.

## Methodology

### Signal
```
1. Compute Bollinger Bands: period=20, std=2.0
2. Signal: price was below lower BB last bar, now closed above it (the "bounce")
3. Entry: next bar open (standard engine behavior)
4. Additional filters tested:
   - SMA200: only trade when close > SMA(200) (uptrend pullbacks)
   - Various stop/target/hold combinations
```

### Data
- OKX BTC/USDT 1h: 2019-2026 (~65k bars)
- Binance BTC/USDT 1h: 2019-2026 (~65k bars)
- Commission: 5 bps round-trip, Slippage: 5 bps

### Regime Analysis
Tagged every trade (1,506 total) with market conditions at entry:
- SMA200, SMA50: trend regime
- ADX, PDI, MDI: trend strength and direction
- RSI(14): momentum
- ATR ratio: volatility regime
- 48h price change: recent drawdown
- Hour of day: session effects

### Validation
1. Full-period backtest on OKX
2. Walk-forward validation (7 splits)
3. Cross-validation on Binance
4. Exit optimization: target/hold/stop sweep

## Results

### Simple BB Lower Band Bounce (baseline, no filters)

```
Initial Capital:    10,000 USDT
Commission:         5 bps (round-trip)
Slippage:           5 bps

Total Trades:       1,506
Compound Return:    -84.5%
Linear Sum:         -164.5%
Annualized Return:  -22.2%
Sharpe Ratio:       -0.87
Sortino Ratio:      -0.72
Max Drawdown:       88.1%
Win Rate:           51.1%
Avg Win:            +1.255%
Avg Loss:           -1.536%
Profit Factor:      0.85
Max Consec Losses:  10
Avg MFE:            +1.337%
Avg MAE:            -1.523%

Exit Breakdown:
  take_profit:   261 (17.3%)  avg=+2.45%  total=+639.1%
  stop_loss:     356 (23.6%)  avg=-2.55%  total=-907.3%
  time_exit:     889 (59.0%)  avg=+0.12%  total=+103.8%
```

**Key observation:** 59% of trades are time-exits with near-zero average (+0.12%). The signal doesn't reliably bounce — it drifts sideways and expires. The 23.6% stop-loss rate with avg -2.55% loss overwhelms the 17.3% take-profit rate.

### SMA200 Filter (above SMA only)

```
Total Trades:       485
Compound Return:    -37.6%
Linear Sum:         -41.0%
Sharpe Ratio:       -0.43
Max Drawdown:       46.7%
Win Rate:           50.9%
Profit Factor:      0.87

Exit Breakdown:
  take_profit:    73 (15.1%)  avg=+2.45%
  stop_loss:      93 (19.2%)  avg=-2.55%
  time_exit:     319 (65.8%)  avg=+0.05%
```

The SMA200 filter reduces trade count by 68% but still negative. The problem is fundamental — even in uptrend pullbacks, lower BB touches don't reliably bounce.

### Exit Optimization (SMA200 filtered)

#### Target Sweep (s2.5%, h12h)

| Target | Trades | Sum | Sharpe | WR | PF |
|--------|--------|-----|--------|----|----|
| 1.0% | 495 | +17.1% | +0.24 | 64.8% | 1.07 |
| 1.5% | 486 | -11.8% | -0.14 | 57.2% | 0.96 |
| 2.5% | 485 | -41.0% | -0.43 | 50.9% | 0.87 |
| 5.0% | 484 | -61.7% | -0.61 | 50.0% | 0.82 |

**Finding:** Target must be ≤ 1.0% to stay positive — the "bounce" is tiny.

#### Best Configuration: s2.5% / t1.0% / h10h

```
Total Trades:       503
Compound Return:    +15.9%
Annualized Return:  +2.0%
Sharpe Ratio:       +0.26
Sortino Ratio:      +0.12
Max Drawdown:       14.3%
Win Rate:           61.2%
Avg Win:            +0.796%
Avg Loss:           -1.164%
Profit Factor:      1.08
Max Consec Losses:  5

Exit Breakdown:
  take_profit:   237 (47.1%)  avg=+0.95%  total=+225.0%
  stop_loss:      58 (11.5%)  avg=-2.55%  total=-147.8%
  time_exit:     208 (41.4%)  avg=-0.28%  total= -59.0%
```

Even the best configuration is marginal: Sharpe +0.26, PF 1.08. The 1.0% target means after 5 bps commission, net profit is only ~0.9% — barely above breakeven.

### Regime Analysis

#### SMA200 — THE DOMINANT DIMENSION

| Regime | Trades | Sum | Sharpe | WR | PF |
|--------|--------|-----|--------|-----|-----|
| Above SMA200 | 482 | -1.7% | -0.05 | 53.7% | 0.99 |
| Below SMA200 | 1,020 | -168.4% | -2.99 | 49.7% | 0.80 |

**Finding:** 68% of trades occur below SMA200 with catastrophic results. Even above SMA200, the edge is negligible (Sharpe -0.05).

#### Directional Movement — THE ONLY POSITIVE REGIME

| Regime | Trades | Sum | Sharpe | WR | PF |
|--------|--------|-----|--------|-----|-----|
| PDI > MDI (bullish) | 110 | +35.6% | +2.14 | 58.2% | 1.67 |
| PDI ≤ MDI (bearish) | 1,396 | -200.1% | -3.12 | 50.6% | 0.81 |

**Finding:** PDI > MDI is the ONLY regime where the signal works — but it's only 7.3% of trades. 93% of signals fire in bearish conditions where it loses money. The signal is NOT mean-reversion — it only works when the market is already going up.

#### RSI — OVERSOLD IS TOXIC, STRONG IS GOOD

| Regime | Trades | Sum | Sharpe | WR | Stop Rate |
|--------|--------|-----|--------|-----|-----------|
| RSI < 30 (oversold) | 253 | -180.0% | -6.28 | 37.5% | 41.9% |
| RSI 30-40 | 565 | -147.9% | -3.59 | 47.3% | 27.1% |
| RSI 40-50 | 552 | +80.2% | +2.18 | 57.8% | 15.2% |
| RSI > 50 | 136 | +83.3% | +4.63 | 65.4% | 9.6% |

**Finding:** The signal works BETTER when RSI is higher — this is the opposite of mean reversion. Buying "oversold" (RSI < 30) produces a 41.9% stop rate. The "bounce" doesn't happen in crashes.

#### 48h Drawdown — CRASHES KEEP CRASHING

| Regime | Trades | Sum | Sharpe | WR | Stop Rate |
|--------|--------|-----|--------|-----|-----------|
| Crash (< -5%) | 421 | -162.5% | -3.88 | 44.2% | 41.1% |
| Drop (-5 to -2%) | 671 | -66.6% | -1.57 | 51.1% | 20.4% |
| Flat (-2 to 0%) | 404 | +47.2% | +1.73 | 57.7% | 11.4% |
| Up (> 0%) | 9 | +14.9% | +4.12 | 77.8% | 0.0% |

**Finding:** After a 48h crash, the stop rate is 41.1%. The lower BB touch during a crash is NOT a buying opportunity — it's a continuation signal.

#### Combined Toxic Regimes

| Regime | Trades | Sum | Sharpe | PF |
|--------|--------|-----|--------|-----|
| Below SMA200 + PDI≤MDI | 974 | -178.3% | -3.23 | 0.78 |
| Below SMA200 + ADX>25 | 669 | -124.3% | -2.66 | 0.78 |
| 48h crash (< -5%) | 421 | -162.5% | -3.88 | 0.65 |

### Walk-Forward Validation

#### Baseline (unfiltered)
```
Split  Period              Trades   Sum      Sharpe
1      2019-10→2020-08     157      -22.1%   -1.25  ❌
2      2020-08→2021-06     183      -40.8%   -1.48  ❌
3      2021-06→2022-04     191      -37.5%   -1.35  ❌
4      2022-04→2023-02     172       -6.8%   -0.29  ❌
5      2023-02→2023-12     162      -15.9%   -1.01  ❌
6      2023-12→2024-10     155      -30.5%   -1.54  ❌
7      2024-10→2025-08     165      +11.7%   +0.68  ✅

1/7 OOS profitable | Mean OOS Sharpe: -0.89
```

#### Optimized (SMA200 + s2.5/t1.0/h10)
```
Split  Period              Trades   Sum      Sharpe
1      2019-10→2020-08      52       -0.9%   -0.12  ❌
2      2020-08→2021-06      79      +12.8%   +1.17  ✅
3      2021-06→2022-04      53       -4.4%   -0.50  ❌
4      2022-04→2023-02      45       +0.1%   +0.02  ✅
5      2023-02→2023-12      56       +6.2%   +1.07  ✅
6      2023-12→2024-10      65       -0.1%   -0.02  ❌
7      2024-10→2025-08      59       +5.6%   +0.82  ✅

4/7 OOS profitable | Mean OOS Sharpe: +0.35
```

**Even the optimized version only achieves 4/7 splits profitable with mean Sharpe +0.35.**

### Binance Cross-Validation

| Metric | OKX Baseline | Binance Baseline | OKX Opt | Binance Opt* |
|--------|-------------|------------------|---------|-------------|
| Trades | 1,506 | 1,503 | 503 | — |
| Sharpe | -0.87 | -0.94 | +0.26 | — |
| Max DD | 88.1% | 89.7% | 14.3% | — |
| PF | 0.85 | 0.84 | 1.08 | — |

Both exchanges confirm the same finding: the strategy doesn't work.

### Binance Walk-Forward (SMA200 filtered)
```
2/7 OOS profitable | Mean OOS Sharpe: -0.32 | Total OOS: -26.3%
```

## Analysis

### Why Does This Fail?

1. **Mean reversion doesn't work on 1h BTC.** This is consistent with the RSI(2) mean-reversion failure (Sharpe -3.57) documented in the findings registry. At the 1-hour scale, Bitcoin trends — it doesn't mean-revert.

2. **The "bounce" is a momentum continuation, not reversion.** The signal only works when PDI > MDI (bullish direction) and RSI > 40 (not oversold). These are momentum conditions, not mean-reversion conditions. The lower BB touch in an uptrend is a pullback entry — buying strength, not weakness.

3. **Crashes don't bounce.** RSI < 30 has a 41.9% stop rate. 48h crash (<-5%) has a 41.1% stop rate. When Bitcoin is falling, lower BB touches are NOT buying opportunities — they're early entries into continuing declines.

4. **68% of signals fire in bearish regimes.** Below SMA200 + PDI≤MDI dominates (974/1506 trades). The signal's natural habitat is the worst possible condition for it.

5. **The edge is tiny even when it works.** The best configuration targets 1.0% profit. After 5 bps commission, net is ~0.9%. With a 2.5% stop, the risk:reward is 1:0.36 — you need a very high win rate to overcome this, and 61% isn't enough.

### Comparison with BB Upper Breakout

| Metric | Upper Breakout (Momentum) | Lower Reversion |
|--------|--------------------------|-----------------|
| Signal type | Momentum/continuation | Attempted mean-reversion |
| Best Sharpe | +1.38 | +0.26 |
| Max DD | -21.4% | -14.3% (optimized) |
| WF profitable | 6/7 | 4/7 |
| Mean WF Sharpe | +1.12 | +0.35 |
| Deployable? | ✅ Yes | ❌ No |

**The BB Upper Breakout works because it buys STRENGTH (momentum continuation). The Lower Reversion fails because it buys WEAKNESS — and in crypto, weakness tends to continue.**

### Fundamental Insight

This research confirms a pattern across our strategy library:

| Strategy | Signal Type | Works? | Best Sharpe |
|----------|------------|--------|-------------|
| BB Upper Breakout | Momentum/continuation | ✅ | +1.38 |
| Spring Reversal (filtered) | Trend pullback (not mean-reversion) | ✅ | +1.53 |
| Wick Inversion (filtered) | Seller exhaustion in uptrends | ⚠️ | +0.87 |
| RSI(2) Mean Reversion | Pure mean reversion | ❌ | -1.62 |
| BB Lower Reversion | Pure mean reversion | ❌ | +0.26 |

**The strategies that work are MOMENTUM or TREND-FOLLOWING signals masquerading as something else.** Spring Reversal works not because it buys oversold conditions but because it buys pullbacks in uptrends (Above SMA200 + BB bounce zone). Wick Inversion works not because it detects seller exhaustion but because it detects failed selling in uptrends. Pure mean-reversion strategies consistently fail on 1h crypto.

## Recommendation

### ❌ DISCARD

**Do not implement BB Lower Band Mean Reversion as a standalone strategy.**

**Rationale:**
- Best Sharpe +0.26 is not deployable (threshold: +1.0)
- Only 4/7 walk-forward profitable
- 68% of signals fire in toxic regimes
- Risk:reward ratio is unfavorable (1:0.36)
- Consistent with RSI(2) mean-reversion failure

### What This Teaches Us

1. **1h BTC does not mean-revert.** Stop trying pure mean-reversion strategies.
2. **Buying weakness is dangerous in crypto.** All our successful strategies buy strength in some form.
3. **Pullback entries in uptrends work, but they're not mean-reversion.** They're trend-following entries at better prices.
4. **The "lower the target" pattern has limits.** Even at 1.0% target, the strategy barely breaks even.

### Alternative Approaches Worth Exploring

1. **BB Lower Band as a FILTER for existing strategies** — use lower BB touch as a cooldown/avoidance signal instead of an entry signal
2. **15-minute timeframe** — mean reversion may work at shorter timeframes where noise creates more temporary dislocations
3. **Funding rate mean reversion** — a different kind of "reversion" unique to crypto that doesn't rely on price action
4. **Cross-asset pairs** — ETH/BTC ratio mean reversion may work better than absolute price mean reversion

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant
python research/backtest_bb_lower_reversion.py
```

**Data:** OKX BTC/USDT 1h (2019-2026, ~65k bars)
**Commission:** 5 bps round-trip
**Slippage:** 5 bps

---

**Document version:** v1
**Date:** 2026-06-15
**Author:** CryptoQuant Autonomous Researcher
**Status:** ❌ DISCARD — documented failure, valuable for findings registry
