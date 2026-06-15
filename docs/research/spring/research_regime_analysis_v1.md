# Spring Reversal — Comprehensive Regime Analysis v1

> **One-line summary:** The Spring Reversal baseline is broken (Sharpe -0.71, MaxDD -55%). SMA200 + BB %B 0.2-0.6 filter transforms it to Sharpe +1.53, MaxDD -5.5%, 5/6 walk-forward profitable. The signal only works above SMA200 and in the BB bounce zone (%B 0.2-0.6).

## Hypothesis

The Spring Reversal strategy detects Wyckoff Spring patterns — failed breakdowns where price makes a new low but closes bullish with high volume. Previous research found that BB %B 0.2-0.6 + SMA200 filter produced Sharpe 2.72 on a small subset of trades. However, no comprehensive regime analysis had been done to understand which market conditions make the signal work or fail.

**Hypothesis:** The Spring signal has edge in specific market regimes (above SMA200, in BB bounce zone) but is toxic in others (below SMA200, RSI < 30, strong bull markets). Identifying and filtering toxic regimes can transform the strategy from unprofitable to deployable.

## Methodology

1. Ran full backtest on OKX BTC/USDT 1h (2019-2026, 65,016 bars)
2. Tagged every trade (543 total) with market conditions at entry:
   - SMA200, SMA50, EMA50/EMA200: trend regime
   - ADX, PDI, MDI: trend strength and direction
   - RSI(14): momentum
   - Bollinger %B: position within bands
   - 48h, 24h price change: recent momentum
   - ATR ratio: volatility regime
   - Day of week, hour of day: session effects
   - 200-day return: macro trend
3. Grouped trades by regime and compared performance
4. Tested combined regimes to find toxic combinations
5. Walk-forward validated promising filters (6 splits)
6. Cross-validated on Binance BTC/USDT 1h
7. Grid search: 6 stops × 9 targets × 6 holds = 324 combinations for best filter

**Critical:** Always used `lows[i]` for stop checking (not `closes[i]`).

## Results

### Baseline Performance (OKX BTC/USDT 1h, 2019-2026)

```
Total Trades:       543
Compound Return:    -46.0%
Linear Sum:         -43.2%
Sharpe (per-trade): -0.71
Sortino:            -1.58
Win Rate:           48.1%
Avg Win:            +2.14%
Avg Loss:           -2.13%
Profit Factor:      0.93
Max Drawdown:       -55.0%
Max Consec Losses:  8

Exit Breakdown:
  take_profit:   59 (10.9%)  avg=+4.90%  total=+289.0%
  stop_loss:    157 (28.9%)  avg=-3.10%  total=-486.5%
  time_exit:    327 (60.2%)  avg=+0.47%  total=+154.3%
```

**Key observation:** 60.2% of trades are time-exits with avg +0.47%. 98.2% of time-exits were profitable at some point (mean MFE +1.93%). This is the classic "lower the target" pattern — the signal produces small moves that expire before reaching the 5% target.

### Single-Dimension Regime Analysis

#### 1. SMA200 — THE DOMINANT REGIME DIMENSION

| Regime | Trades | Sum | Sharpe | Win Rate | PF | Stop Rate |
|--------|--------|-----|--------|----------|-----|-----------|
| Above SMA200 | 156 | +4.9% | +0.15 | 47.4% | 1.03 | 23.1% |
| Below SMA200 | 387 | -48.1% | -0.93 | 48.3% | 0.89 | 31.3% |

**Finding:** The signal is marginally positive above SMA200 and deeply negative below. 71% of trades occur below SMA200 — the signal fires most often in the worst regime.

#### 2. Bollinger %B — THE SWEET SPOT

| Regime | Trades | Sum | Sharpe | Win Rate | PF | Stop Rate |
|--------|--------|-----|--------|----------|-----|-----------|
| %B < 0 (below lower) | 87 | -54.1% | -2.34 | 39.1% | 0.54 | 35.6% |
| %B 0-0.2 | 221 | -98.0% | -2.60 | 41.6% | 0.66 | 34.8% |
| **%B 0.2-0.4** | **132** | **+66.5%** | **+2.18** | **57.6%** | **1.62** | **21.2%** |
| **%B 0.4-0.6** | **60** | **+33.1%** | **+1.68** | **60.0%** | **1.69** | **16.7%** |
| %B 0.6-0.8 | 20 | +8.5% | +0.77 | 55.0% | 1.53 | 20.0% |
| %B 0.8-1.0 | 13 | +2.9% | +0.29 | 53.8% | 1.22 | 23.1% |
| %B >= 1.0 | 10 | -2.1% | -0.23 | 50.0% | 0.85 | 40.0% |

**Finding:** The signal works best in the BB bounce zone (%B 0.2-0.6). Below 0.2 is toxic (crash territory). Above 0.8 is too extended. This makes sense: a Spring reversal needs price to be near support, not in free-fall or at resistance.

#### 3. RSI(14) — OVERSOLD IS TOXIC

| Regime | Trades | Sum | Sharpe | Win Rate | Stop Rate |
|--------|--------|-----|--------|----------|-----------|
| RSI < 30 (oversold) | 90 | -73.1% | -2.84 | 32.2% | 47.8% |
| RSI 30-40 | 197 | -18.2% | -0.49 | 49.2% | 29.9% |
| RSI 40-50 | 179 | +28.6% | +0.87 | 52.5% | 20.1% |
| RSI 50-60 | 69 | +19.4% | +0.89 | 53.6% | 23.2% |

**Finding:** The signal is a reversal signal that works best when price is NOT oversold. RSI < 30 has 47.8% stop rate — the "breakdown" in oversold conditions is a genuine breakdown, not a trap.

#### 4. ADX — RANGING IS BEST

| Regime | Trades | Sum | Sharpe | Win Rate | PF | Stop Rate |
|--------|--------|-----|--------|----------|-----|-----------|
| ADX > 30 (very strong) | 234 | -30.8% | -0.72 | 46.6% | 0.89 | 34.6% |
| ADX 25-30 (strong) | 80 | -7.6% | -0.34 | 48.8% | 0.91 | 26.2% |
| ADX 20-25 (moderate) | 106 | -39.4% | -1.58 | 41.5% | 0.69 | 29.2% |
| **ADX <= 20 (weak/ranging)** | **123** | **+34.5%** | **+1.28** | **56.1%** | **1.34** | **19.5%** |

**Finding:** Counterintuitively, the Spring reversal works best in ranging markets (ADX <= 20), not in strong trends. In strong trends, the "breakdown" is a genuine trend continuation, not a trap.

#### 5. 200-Day Return (Macro Trend)

| Regime | Trades | Sum | Sharpe | Win Rate | PF | Stop Rate |
|--------|--------|-----|--------|----------|-----|-----------|
| Bear (<-20%) | 96 | +21.8% | +0.77 | 51.0% | 1.21 | 31.2% |
| Weak bear (-20 to 0%) | 63 | +13.8% | +0.71 | 54.0% | 1.26 | 19.0% |
| Weak bull (0 to 50%) | 220 | +11.9% | +0.33 | 50.9% | 1.06 | 22.3% |
| Bull (50 to 200%) | 111 | -48.0% | -1.80 | 41.4% | 0.66 | 35.1% |
| **Strong bull (>200%)** | **35** | **-32.7%** | **-1.77** | **31.4%** | **0.53** | **60.0%** |

**Finding:** The signal is toxic in strong bull markets (200-day return > 200%). In parabolic rallies, every "breakdown" is a buying opportunity for trend followers, not a reversal.

#### 6. PDI vs MDI

| Regime | Trades | Sum | Sharpe | Win Rate | PF |
|--------|--------|-----|--------|----------|-----|
| PDI > MDI (bullish) | 48 | +11.0% | +0.64 | 56.2% | 1.26 |
| PDI <= MDI (bearish) | 495 | -54.2% | -0.93 | 47.3% | 0.90 |

**Finding:** Only 48 trades (8.8%) occur when PDI > MDI, but they're profitable. The signal fires overwhelmingly in bearish directional conditions.

#### 7. Volatility (ATR ratio)

| Regime | Trades | Sum | Sharpe | Win Rate | PF |
|--------|--------|-----|--------|----------|-----|
| Very Low (<0.6) | 18 | -13.9% | -1.90 | 50.0% | 0.33 |
| Low (0.6-0.8) | 71 | -13.1% | -0.59 | 45.1% | 0.85 |
| Normal (0.8-1.2) | 268 | -6.8% | -0.17 | 49.3% | 0.97 |
| High (1.2-1.5) | 88 | -32.5% | -1.38 | 42.0% | 0.70 |
| **Very High (>1.5)** | **98** | **+23.0%** | **+0.76** | **52.0%** | **1.20** |

**Finding:** Counterintuitive — very high volatility is the best regime. In high-vol environments, the "failed breakdown" signal is more meaningful because the trap is more dramatic.

### Combined Regime Analysis

| Regime | Trades | Sum | Sharpe | WR | PF | Stop Rate |
|--------|--------|-----|--------|----|----|-----------|
| **Above SMA200 + %B 0.2-0.6** | **57** | **+47.8%** | **+2.64** | **61.4%** | **2.48** | **8.8%** |
| Above SMA200 + PDI > MDI | 27 | +21.8% | +1.79 | 66.7% | 2.30 | 14.8% |
| Above SMA200 + RSI 40-60 | 99 | +26.0% | +1.07 | 51.5% | 1.31 | 17.2% |
| Below SMA200 + %B 0.2-0.6 | 135 | +51.8% | +1.65 | 57.0% | 1.42 | 24.4% |
| Below SMA200 + %B < 0.2 | 229 | -103.4% | -2.69 | 43.2% | 0.65 | 35.8% |
| Above SMA200 + %B < 0.2 | 79 | -48.7% | -2.23 | 34.2% | 0.55 | 32.9% |
| Below SMA200 + PDI <= MDI | 366 | -37.3% | -0.74 | 48.6% | 0.91 | 31.1% |

**Key Finding:** 
- **Above SMA200 + %B 0.2-0.6** is the best combined regime: Sharpe +2.64, PF 2.48, MaxDD -10.8%, only 8.8% stop rate
- **Below SMA200 + %B < 0.2** is toxic: Sharpe -2.69, PF 0.65, 35.8% stop rate
- Interestingly, Below SMA200 + %B 0.2-0.6 is also profitable (+1.65 Sharpe) — the BB zone matters more than SMA200 alone

### Filter Comparison (Post-Hoc)

| Filter | Trades | Sum | Sharpe | WR | PF | MaxDD | Compound |
|--------|--------|-----|--------|----|----|-------|----------|
| Baseline (no filter) | 543 | -43.2% | -0.71 | 48.1% | 0.93 | -55.0% | -46.0% |
| SMA200 only | 156 | +4.9% | +0.15 | 47.4% | 1.03 | -21.1% | -0.1% |
| PDI > MDI only | 48 | +11.0% | +0.64 | 56.2% | 1.26 | -9.7% | +10.0% |
| **SMA200 + %B 0.2-0.6** | **57** | **+47.8%** | **+2.64** | **61.4%** | **2.48** | **-10.8%** | **+58.4%** |
| SMA200 + PDI > MDI | 27 | +21.8% | +1.79 | 66.7% | 2.30 | -6.8% | +23.4% |
| SMA200 + PDI>MDI + ADX>25 | 10 | +12.8% | +2.05 | 70.0% | 5.74 | -1.7% | +13.4% |
| 48h > 0% only | 126 | +16.5% | +0.59 | 50.0% | 1.14 | -18.1% | +13.4% |

**Key Finding:** SMA200 + %B 0.2-0.6 is the best filter by a wide margin. It has the highest Sharpe (+2.64), highest PF (2.48), and highest compound return (+58.4%).

### Exit Optimization (SMA200 + BB 0.2-0.6 filter)

Grid search: 6 stops × 9 targets × 6 holds = 324 combinations.

**Top 5 by Sharpe:**

| Stop | Target | Hold | Trades | Sum | Sharpe | WR | PF | MaxDD |
|------|--------|------|--------|-----|--------|----|----|-------|
| **3.0%** | **3.0%** | **16h** | **78** | **+24.5%** | **+1.53** | **56.4%** | **1.53** | **-5.5%** |
| 3.0% | 3.0% | 32h | 72 | +28.8% | +1.43 | 59.7% | 1.44 | -9.4% |
| 3.0% | 2.5% | 24h | 74 | +24.5% | +1.43 | 58.1% | 1.45 | -6.7% |
| 3.0% | 2.5% | 32h | 72 | +26.9% | +1.42 | 61.1% | 1.43 | -6.8% |
| 3.5% | 3.0% | 16h | 78 | +23.1% | +1.41 | 56.4% | 1.49 | -6.3% |

**Best configuration: stop=3.0%, target=3.0%, hold=16h**

The "lower the target" pattern is confirmed: lowering target from 5.0% to 3.0% dramatically improves results. 96.4% of time-exits were profitable at some point (mean MFE +1.56%), but the 5% target was too far. At 3%, the take-profit rate increases and time-exits become less frequent.

### Best Configuration — Full Backtest (OKX BTC/USDT 1h, 2019-2026)

```
Initial Capital:    10,000 USDT
Commission:         5 bps (round-trip)
Slippage:           5 bps

Total Trades:       78
Compound Return:    +26.0%
Linear Sum:         +24.5%
Sharpe Ratio:       +1.53
Sortino Ratio:      +2.62
Max Drawdown:       -5.5%
Win Rate:           56.4%
Avg Win:            +1.61%
Avg Loss:           -1.36%
Profit Factor:      1.53
Max Consec Losses:  4

Exit Breakdown:
  take_profit:   15 (19.2%)  avg=+2.90%  total=+43.5%
  stop_loss:      8 (10.3%)  avg=-3.10%  total=-24.8%
  time_exit:     55 (70.5%)  avg=+0.10%  total=+5.8%

MFE:
  Mean:   +1.56%
  Median: +1.20%
  Max:    +7.88%

Time-exit trades profitable at some point: 53/55 (96.4%)
```

### Walk-Forward Validation (OKX, 6 splits)

| Split | Period | Trades | Sum | Sharpe | Status |
|-------|--------|--------|-----|--------|--------|
| 1 | 2019-12→2020-11 | 13 | +11.6% | +1.76 | ✅ |
| 2 | 2020-11→2021-10 | 4 | +4.6% | +0.93 | ✅ |
| 3 | 2021-10→2022-09 | 10 | -2.4% | -0.37 | ❌ |
| 4 | 2022-09→2023-08 | 10 | +0.6% | +0.13 | ✅ |
| 5 | 2023-08→2024-07 | 19 | +4.6% | +0.69 | ✅ |
| 6 | 2024-07→2025-06 | 12 | +4.5% | +0.74 | ✅ |

**5/6 OOS profitable | Mean OOS Sharpe: +0.65 | Total OOS Sum: +23.6%**

### Binance Cross-Validation

| Metric | OKX | Binance |
|--------|-----|---------|
| Trades | 78 | 86 |
| Sum | +24.5% | +37.2% |
| Sharpe | +1.53 | +2.34 |
| Max DD | -5.5% | -5.4% |
| Win Rate | 56.4% | 60.5% |
| Profit Factor | 1.53 | 1.85 |

Binance walk-forward: **4/6 profitable**, Mean OOS Sharpe: +0.89.

### Filter Necessity: SMA200 is Critical

| Filter | Trades | Sum | Sharpe | WR | PF | MaxDD |
|--------|--------|-----|--------|----|----|-------|
| BB 0.2-0.6 only (no SMA200) | 227 | -2.7% | -0.09 | 53.3% | 0.99 | -18.8% |
| BB 0.2-0.6 + SMA200 | 78 | +24.5% | +1.53 | 56.4% | 1.53 | -5.5% |

Without SMA200, the BB filter alone doesn't work — 227 trades with -0.09 Sharpe. The SMA200 filter eliminates the toxic below-SMA200 trades that dominate the BB 0.2-0.6 zone.

### Consecutive Loss Analysis

| After N Losses | Trades | Avg PnL | Win Rate |
|----------------|--------|---------|----------|
| 1 | 124 | -0.11% | 44.4% |
| 2 | 69 | -0.30% | 43.5% |
| 3 | 39 | -0.56% | 38.5% |
| 4 | 23 | +0.22% | 47.8% |
| 5 | 12 | -1.06% | 25.0% |

**Finding:** Performance degrades after consecutive losses. After 3 losses, win rate drops to 38.5%. A consecutive-loss cooldown (pause after 3 losses) could improve results but would further reduce already-low trade count.

## Analysis

### Why Does the Spring Signal Fail Without Filters?

1. **71% of signals fire below SMA200.** The Spring pattern detects "failed breakdowns" — but in a downtrend, most breakdowns are genuine, not traps. The signal is buying into a falling knife.

2. **60% of trades are time-exits.** The 5% target is too far for the typical Spring move (mean MFE +1.93%). The signal produces small bounces that expire before reaching the target.

3. **RSI < 30 is a death zone.** When RSI is oversold, the "breakdown" is a genuine continuation, not a Spring. 47.8% stop rate confirms this.

4. **Strong bull markets are toxic.** In parabolic rallies (200-day return > 200%), every dip is bought by trend followers. The Spring signal is fighting the trend.

### Why Does SMA200 + BB 0.2-0.6 Work?

1. **SMA200 eliminates downtrend entries.** Above SMA200, the market is in an uptrend. A "breakdown" in an uptrend is more likely to be a trap (shaking out weak hands) than a genuine reversal.

2. **BB 0.2-0.6 identifies the bounce zone.** This is where price is near the lower Bollinger Band but not in free-fall. It's the classic "buy the dip" zone in an uptrend.

3. **Lower target (3.0% vs 5.0%) captures the typical move.** The mean MFE is +1.56% with median +1.20%. A 3.0% target captures the upper tail of these moves without being unreachable.

4. **16h hold is the sweet spot.** Shorter holds (6-10h) cut winners short. Longer holds (24-48h) let profits evaporate. 16h captures the typical Spring bounce duration.

### Limitations

1. **Low trade count.** 78 trades over 7 years = ~11 trades/year. This is sparse. Walk-forward splits have as few as 4 trades, making statistical significance questionable.

2. **One bad walk-forward split.** Split 3 (2021-10→2022-09, the 2022 bear market) is negative. During this period, price spent most time below SMA200, so the filter blocked most trades. The few that fired were in brief bear market rallies that failed.

3. **Binance WF is 4/6, not 5/6.** The cross-validation is slightly weaker, suggesting some exchange-specific effects.

4. **Post-hoc vs walk-forward gap.** Post-hoc Sharpe +2.64 vs WF mean +0.65 is a large gap, indicating some overfitting to the in-sample period.

5. **No multi-pair validation.** Only tested on BTC/USDT. The signal may not work on altcoins.

6. **The baseline is genuinely broken.** Sharpe -0.71, MaxDD -55%. This is not a marginal strategy that needs tuning — it's a losing strategy that needs regime filters to become profitable.

### Comparison with Wick Inversion Regime Analysis

| Aspect | Wick Inversion | Spring Reversal |
|--------|---------------|-----------------|
| Baseline Sharpe | +0.41 (marginal) | -0.71 (broken) |
| Best Filter | SMA200 + PDI>MDI | SMA200 + BB 0.2-0.6 |
| Best Post-Hoc Sharpe | +3.75 | +2.64 |
| Best WF Mean Sharpe | +1.07 | +0.65 |
| WF Profitable Splits | 5/6 | 5/6 |
| Trades (filtered) | 1,268 | 78 |
| Signal Type | Momentum/continuation | Reversal |

The Wick regime analysis found that Wick is a momentum signal (works best in uptrends). The Spring regime analysis finds that Spring is a reversal signal that only works in uptrends — it needs the trend to be intact for the "failed breakdown" to be meaningful.

## Recommendation

### 🔬 MORE RESEARCH NEEDED — Not yet deployable

**Rationale:**
- Post-hoc Sharpe +2.64 is excellent, but WF mean Sharpe +0.65 is below the deployment threshold (≥1.0)
- Only 78 trades over 7 years — too sparse for confident deployment
- Binance WF is 4/6, not 5/6 — weaker cross-validation
- The gap between post-hoc and WF (+2.64 vs +0.65) suggests overfitting

**What works:**
- SMA200 filter is essential — without it, the strategy is broken
- BB %B 0.2-0.6 identifies the bounce zone where Springs are profitable
- Lower target (3.0% vs 5.0%) dramatically improves results
- 16h hold captures the typical Spring bounce duration

**What needs more work:**
1. **Increase trade count.** The 78 trades over 7 years is too sparse. Consider:
   - Multi-pair deployment (ETH, SOL, etc.) to increase trade frequency
   - Relaxing the BB %B filter slightly (e.g., 0.15-0.65) to capture more trades
   - Testing on 4h timeframe for higher-quality, fewer but more reliable signals

2. **Address the bear market split.** Split 3 (2022 bear) is negative. Consider:
   - Adding a 200-day return filter (avoid when 200d return > 100%)
   - Dynamic position sizing (reduce size when macro trend is weakening)

3. **Test consecutive-loss cooldown.** After 3 consecutive losses, win rate drops to 38.5%. A 1-2 bar cooldown could prevent chasing losing streaks.

4. **Combine with BB Upper Breakout.** The Spring works in ranging/pullback conditions. BB Breakout works in momentum conditions. They should be complementary.

### If Deploying Today

Use the best configuration for paper trading:
```
Signal: Spring Reversal (lookback=20, vol_mult=1.5, close_pct=0.5)
Filters: close > SMA(200) AND BB %B in [0.2, 0.6)
Stop: 3.0% (lows-based)
Target: 3.0%
Hold: 16 hours
Commission: 5 bps, Slippage: 5 bps
```

Expected performance: Sharpe +0.5 to +1.0, MaxDD -5% to -15%, ~10-15 trades/year on BTC.

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant

# Full regime analysis
python research/backtest_spring_regime_analysis.py

# Exit optimization for best filter
python research/backtest_spring_exit_optimization.py
```

**Data:** OKX + Binance BTC/USDT 1h (2019-2026, ~65k bars each)
**Engine:** Custom regime_backtest() with lows-based stop checking
**Commission:** 5 bps (round-trip)
**Slippage:** 5 bps

---

**Document version:** v1
**Date:** 2026-06-15
**Author:** CryptoQuant Autonomous Researcher
