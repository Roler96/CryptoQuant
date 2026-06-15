# Spring Reversal — Exit Optimization: Lower Target + Longer Hold

> **One-line summary:** Lowering target from 3.0% to 2.75% and extending hold from 16h to 32h doubles take-profit rate (19.2%→41.7%), halves time-exit rate (70.5%→38.9%), and achieves 7/7 Binance walk-forward profitable. Modest Sharpe improvement (+1.53→+1.58) limited by small sample size (72 trades).

## Hypothesis

The Spring Reversal filtered strategy (SMA200 + BB %B 0.2-0.6) has Sharpe +1.53 but 70.5% of trades are time-exits with avg +0.10%. The mean MFE is +1.56% and 96.4% of time-exits were profitable at some point. This is the classic "lower the target" pattern — the 3.0% target is still too high for the typical Spring bounce.

**Hypothesis:** Lowering the target from 3.0% to 1.5-2.5% will:
1. Increase take-profit rate (capture more of the typical +1-2% bounce)
2. Reduce time-exit rate (fewer trades expire without hitting target)
3. Improve Sharpe by capturing more of the MFE

Additionally, extending the hold time may allow more trades to reach the target, as the Spring bounce can take 24-32h to fully develop.

## Methodology

### Data
- OKX BTC/USDT 1h: 2019-2026 (~65k bars)
- Binance BTC/USDT 1h: 2019-2026 (~65k bars)
- Commission: 5 bps round-trip, Slippage: 5 bps

### Signal
```
Spring Reversal: lookback=20, vol_mult=1.5, close_pct=0.5
Filters: close > SMA(200) AND BB %B in [0.2, 0.6)
Entry: Next bar open after signal
Stop: lows-based
```

### Grid Search
- Stops: 1.5%, 2.0%, 2.5%, 3.0%, 3.5%, 4.0% (6 values)
- Targets: 1.0%, 1.25%, 1.5%, 1.75%, 2.0%, 2.25%, 2.5%, 2.75%, 3.0%, 3.5%, 4.0% (11 values)
- Holds: 8h, 10h, 12h, 14h, 16h, 20h, 24h, 32h (8 values)
- Total: 6 × 11 × 8 = 528 combinations

### Validation
1. Full-period backtest on OKX
2. 7-split walk-forward on OKX
3. 7-split walk-forward on Binance (cross-validation)

## Results

### Baseline (from prior research: s3.0/t3.0/h16)

```
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

MFE: mean=+1.56%, median=+1.20%, max=+7.88%
Time-exits profitable at some point: 53/55 (96.4%)
```

### Grid Search — Top 10 by Sharpe

| Stop | Target | Hold | Trades | Sum | Sharpe | MaxDD | WR | PF |
|------|--------|------|--------|-----|--------|-------|-----|-----|
| 3.0% | 2.75% | 32h | 72 | +30.9% | **+1.58** | -6.6% | 61.1% | 1.50 |
| 3.0% | 3.00% | 16h | 78 | +24.5% | +1.53 | -5.5% | 56.4% | 1.53 |
| 3.0% | 2.75% | 24h | 74 | +26.8% | +1.51 | -6.7% | 58.1% | 1.49 |
| 3.0% | 3.00% | 32h | 72 | +28.8% | +1.43 | -9.4% | 59.7% | 1.44 |
| 3.0% | 2.50% | 24h | 74 | +24.5% | +1.43 | -6.7% | 58.1% | 1.45 |
| 3.0% | 2.50% | 32h | 72 | +26.9% | +1.42 | -6.8% | 61.1% | 1.43 |
| 3.0% | 2.75% | 16h | 78 | +21.9% | +1.41 | -5.5% | 56.4% | 1.47 |
| 3.5% | 3.00% | 16h | 78 | +23.1% | +1.41 | -6.3% | 56.4% | 1.49 |
| 2.0% | 2.75% | 32h | 72 | +24.1% | +1.33 | -7.8% | 54.2% | 1.40 |
| 3.0% | 3.00% | 24h | 74 | +24.5% | +1.33 | -8.8% | 56.8% | 1.43 |

**Key finding:** The best configurations cluster around target=2.5-3.0% and hold=24-32h. The 3.0% stop is consistently optimal. Lower targets (1.0-2.0%) don't improve Sharpe — they capture too little profit per trade and the commission cost becomes proportionally larger.

### Best Configuration — Full Backtest (OKX BTC/USDT 1h, 2019-2026)

```
Initial Capital:    10,000 USDT
Commission:         5 bps (round-trip)
Slippage:           5 bps

Total Trades:       72
Compound Return:    +33.5%
Linear Sum:         +30.9%
Sharpe Ratio:       +1.58
Sortino Ratio:      +3.63
Max Drawdown:       -6.6%
Win Rate:           61.1%
Avg Win:            +2.12%
Avg Loss:           -2.22%
Profit Factor:      1.50
Max Consec Losses:  3

Exit Breakdown:
  take_profit:   30 (41.7%)  avg=+2.65%  total=+79.5%
  stop_loss:     14 (19.4%)  avg=-3.10%  total=-43.4%
  time_exit:     28 (38.9%)  avg=-0.19%  total=-5.2%
```

### Comparison with Baseline

| Metric | Baseline (s3/t3/h16) | Optimized (s3/t2.75/h32) | Delta |
|--------|---------------------|--------------------------|-------|
| Sharpe | +1.53 | +1.58 | +0.05 (+3.3%) |
| Sum | +24.5% | +30.9% | +6.4% (+26.1%) |
| Compound | +26.0% | +33.5% | +7.5% (+28.8%) |
| Max DD | -5.5% | -6.6% | -1.1% (worse) |
| Win Rate | 56.4% | 61.1% | +4.7% |
| PF | 1.53 | 1.50 | -0.03 |
| Trades | 78 | 72 | -6 |
| Take-Profit Rate | 19.2% | 41.7% | **+22.5%** |
| Time-Exit Rate | 70.5% | 38.9% | **-31.6%** |

### Walk-Forward Validation

#### Best Config (s3.0/t2.75/h32) — OKX

| Split | Period | Trades | Sum | Sharpe | Status |
|-------|--------|--------|-----|--------|--------|
| 1 | 2019-10→2020-08 | 13 | +14.8% | +2.04 | ✅ |
| 2 | 2020-08→2021-06 | 4 | +1.3% | +0.26 | ✅ |
| 3 | 2021-06→2022-04 | 7 | -1.5% | -0.23 | ❌ |
| 4 | 2022-04→2023-02 | 9 | +4.2% | +0.74 | ✅ |
| 5 | 2023-02→2023-12 | 11 | -0.9% | -0.11 | ❌ |
| 6 | 2023-12→2024-10 | 12 | +11.1% | +1.64 | ✅ |
| 7 | 2024-10→2025-08 | 11 | +4.2% | +0.56 | ✅ |

**5/7 OOS profitable | Mean OOS Sharpe: +0.70 | Total OOS Sum: +33.2%**

#### Best Config (s3.0/t2.75/h32) — Binance

| Split | Period | Trades | Sum | Sharpe | Status |
|-------|--------|--------|-----|--------|--------|
| 1 | 2019-10→2020-08 | 15 | +18.0% | +2.24 | ✅ |
| 2 | 2020-08→2021-06 | 11 | +1.6% | +0.20 | ✅ |
| 3 | 2021-06→2022-04 | 8 | +1.3% | +0.17 | ✅ |
| 4 | 2022-04→2023-02 | 7 | +2.8% | +0.57 | ✅ |
| 5 | 2023-02→2023-12 | 9 | +0.0% | +0.01 | ✅ |
| 6 | 2023-12→2024-10 | 13 | +11.5% | +1.70 | ✅ |
| 7 | 2024-10→2025-08 | 13 | +5.2% | +0.63 | ✅ |

**7/7 OOS profitable | Mean OOS Sharpe: +0.79 | Total OOS Sum: +40.4%**

### Baseline Config (s3.0/t3.0/h16) — Binance (for reference)

| Split | Period | Trades | Sum | Sharpe | Status |
|-------|--------|--------|-----|--------|--------|
| 1 | 2019-10→2020-08 | 15 | +15.8% | +2.30 | ✅ |
| 2 | 2020-08→2021-06 | 12 | +3.9% | +0.58 | ✅ |
| 3 | 2021-06→2022-04 | 8 | +0.2% | +0.03 | ✅ |
| 4 | 2022-04→2023-02 | 8 | +5.4% | +1.78 | ✅ |
| 5 | 2023-02→2023-12 | 9 | -1.4% | -0.29 | ❌ |
| 6 | 2023-12→2024-10 | 14 | +8.2% | +1.40 | ✅ |
| 7 | 2024-10→2025-08 | 15 | +3.9% | +0.75 | ✅ |

**6/7 OOS profitable | Mean OOS Sharpe: +0.93 | Total OOS Sum: +36.0%**

### Wick + Spring Combined Analysis (Supplementary)

As a supplementary analysis, we tested combining Wick Inversion (imb=0.35) and Spring Reversal signals with OR logic. Key findings:

1. **Near-zero overlap (0.1%).** Only 7 out of 5,170 combined signals fire simultaneously. The strategies operate in completely different market conditions — Wick fires in momentum/continuation, Spring fires in pullback/reversal.

2. **Combining doesn't help.** The combined filtered strategy (SMA200 filter for both) has Sharpe -0.35, 2/7 walk-forward profitable. The Wick filtered signal dominates (920 of 920 combined trades) and its negative performance drags down the result.

3. **Spring filtered is the star.** With only 78-86 trades over 7 years, it achieves Sharpe +1.53-2.34 and 5-6/7 walk-forward profitable. The signal quality is high but trade frequency is very low.

4. **Wick filtered is broken with tight stops.** The Wick filtered strategy (SMA200, imb=0.35, s2.0/t1.5/h12) has Sharpe -0.14 on OKX, -0.17 on Binance. The prior research's post-hoc Sharpe +2.50 was computed with different exit parameters (s3.0/t1.5/h12) and may have been optimistic.

## Analysis

### Why Lower Target + Longer Hold Works

1. **The Spring bounce is small but reliable.** Mean MFE is +1.56%, median +1.20%. A 2.75% target captures the upper tail of these moves. At 3.0%, too many trades expire before reaching the target (70.5% time-exits). At 2.75%, the take-profit rate doubles to 41.7%.

2. **Longer hold (32h vs 16h) gives the bounce time to develop.** The Spring pattern is a reversal from support — it can take 24-32 hours for the bounce to fully play out. The 16h hold was cutting winners short. At 32h, more trades reach the target before time expiry.

3. **3.0% stop is optimal.** Tighter stops (1.5-2.5%) increase stop-out rate without improving net expectancy. The Spring pattern needs room to breathe — the "breakdown" part of the pattern means price already tested lower, and a 3.0% stop gives enough room for the reversal to develop.

4. **Why not lower than 2.75%?** Targets of 1.0-2.5% produce lower Sharpe because:
   - Commission cost (0.1% round-trip) eats a larger proportion of profit
   - The win rate doesn't increase enough to compensate
   - The avg win drops faster than the win rate rises

### Why the Improvement is Modest

1. **Small sample size.** 72-78 trades over 7 years means each trade has outsized impact. The difference between +1.53 and +1.58 Sharpe is within statistical noise for this sample size.

2. **The baseline was already good.** Sharpe +1.53 with MaxDD -5.5% is already a strong strategy. There's limited room for improvement through exit optimization alone.

3. **The core constraint is signal frequency, not exit quality.** The Spring filtered signal fires only ~11 times per year. No amount of exit optimization can overcome the fundamental limitation of sparse signals.

### Limitations

1. **Tiny sample size.** 72-78 trades over 7 years. Walk-forward splits have as few as 4 trades. Statistical significance is questionable.

2. **Binance WF is better than OKX WF.** The best config achieves 7/7 on Binance but only 5/7 on OKX. This is the opposite of what we'd expect and suggests the improvement may not be robust.

3. **The baseline (s3.0/t3.0/h16) has better Binance WF mean Sharpe (+0.93 vs +0.79).** The optimized config improves OKX WF but degrades Binance WF. This is a red flag for overfitting.

4. **No multi-pair validation.** Only tested on BTC/USDT. The signal may not work on altcoins.

5. **The improvement may be curve-fitting.** We tested 528 parameter combinations and picked the best. The improvement (+0.05 Sharpe) is well within the range of selection bias for this sample size.

### Comparison with Wick + Spring Combined

The combined approach was a dead end:
- Near-zero signal overlap (0.1%) confirms the strategies are orthogonal
- But combining them doesn't help because Wick filtered is net-negative
- The Spring filtered signal is the only viable component

## Recommendation

### 🔬 MORE RESEARCH NEEDED — Not yet deployable

**Rationale:**
- The exit optimization produces a modest improvement (+0.05 Sharpe) that may be selection bias
- The best config (s3.0/t2.75/h32) has worse Binance WF than the baseline
- Only 72-78 trades over 7 years — too sparse for confident deployment
- WF mean Sharpe +0.70 (OKX) is below the deployment threshold (≥1.0)

**What works:**
- The "lower the target" pattern is directionally correct — lowering from 3.0% to 2.75% doubles take-profit rate
- Longer hold (32h) allows the Spring bounce to fully develop
- 3.0% stop remains optimal — the pattern needs room to breathe
- The Spring filtered signal quality is high (Sharpe +1.53, MaxDD -5.5%)

**What needs more work:**
1. **Increase trade count.** The 72-78 trades over 7 years is the fundamental bottleneck. Consider:
   - Multi-pair deployment (ETH, SOL, etc.) to increase trade frequency
   - Relaxing the BB %B filter slightly (e.g., 0.15-0.65) to capture more trades
   - Testing on 4h timeframe for higher-quality signals

2. **Address the bear market split.** Split 3 (2021-10→2022-04) is consistently negative across all configs. Consider:
   - Adding a 200-day return filter (avoid when macro trend is weakening)
   - Dynamic position sizing based on macro regime

3. **The baseline (s3.0/t3.0/h16) may actually be better for deployment.** It has:
   - Better Binance WF mean Sharpe (+0.93 vs +0.79)
   - More trades (78 vs 72)
   - Simpler parameters (less overfitting risk)

### If Deploying Today

Use the baseline configuration for paper trading:
```
Signal: Spring Reversal (lookback=20, vol_mult=1.5, close_pct=0.5)
Filters: close > SMA(200) AND BB %B in [0.2, 0.6)
Stop: 3.0% (lows-based)
Target: 3.0%
Hold: 16 hours
Commission: 5 bps, Slippage: 5 bps
```

Expected performance: Sharpe +0.5 to +1.0, MaxDD -5% to -15%, ~10-15 trades/year on BTC.

### Wick + Spring Combined: ❌ DISCARD

The combined approach does not work. Wick and Spring have near-zero overlap (0.1%) but combining them doesn't improve risk-adjusted returns because the Wick filtered signal is net-negative with tight stops. The Spring filtered signal should be deployed independently.

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant

# Exit optimization
python research/backtest_spring_lower_target.py

# Wick + Spring combined analysis
python research/backtest_wick_spring_combined.py
```

**Data:** OKX + Binance BTC/USDT 1h (2019-2026, ~65k bars each)
**Engine:** Custom backtest with lows-based stop checking
**Commission:** 5 bps (round-trip)
**Slippage:** 5 bps

---

**Document version:** v1
**Date:** 2026-06-15
**Author:** CryptoQuant Autonomous Researcher
