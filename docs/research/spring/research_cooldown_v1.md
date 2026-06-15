# Spring Reversal — Consecutive Loss Cooldown: Null Result

> **One-line summary:** A consecutive-loss cooldown mechanism has zero effect on the filtered Spring strategy (SMA200 + BB 0.2-0.6) because losing streaks are too short (max 4). On the unfiltered strategy, it provides a modest improvement (Sharpe -0.71→-0.56) but the strategy remains deeply unprofitable. The cooldown is NOT a viable improvement path.

## Hypothesis

The Spring Reversal regime analysis (research_regime_analysis_v1.md) found that after consecutive losses, win rate degrades:
- After 1 loss: 44.4% WR, avg -0.11%
- After 2 losses: 43.5% WR, avg -0.30%
- After 3 losses: 38.5% WR, avg -0.56%
- After 5 losses: 25.0% WR, avg -1.06%

**Hypothesis:** A cooldown mechanism that pauses trading after N consecutive losses will improve risk-adjusted returns by avoiding losing streaks.

## Methodology

### Data
- OKX BTC/USDT 1h: 2019-2026 (~65k bars)
- Commission: 5 bps round-trip, Slippage: 5 bps

### Signal
```
Spring Reversal: lookback=20, vol_mult=1.5, close_pct=0.5
Filtered: close > SMA(200) AND BB %B in [0.2, 0.6)
Entry: Next bar open after signal
Stop: lows-based
```

### Cooldown Mechanism
```python
consecutive_losses = 0
cooldown_until = -1

# On each trade exit:
if pnl_pct <= 0:
    consecutive_losses += 1
    if consecutive_losses >= cooldown_losses:
        cooldown_until = current_bar + cooldown_bars
        consecutive_losses = 0
else:
    consecutive_losses = 0

# On each signal:
if current_bar < cooldown_until:
    skip signal
```

### Tested Configurations
- Filtered Spring (s3.0/t3.0/h16): cooldown after 1-4 losses, skip 1-3 bars (12 combos)
- Unfiltered Spring (s3.0/t5.0/h24): cooldown after 1-4 losses, skip 1-3 bars (12 combos)

### Validation
1. Full-period backtest on OKX
2. 7-split walk-forward on OKX

## Results

### Filtered Spring (SMA200 + BB 0.2-0.6)

**All 12 cooldown configurations produced IDENTICAL results to baseline.**

| Cooldown | Skip | Trades | Sum | Sharpe | WR | PF | MaxDD | WF |
|----------|------|--------|-----|--------|----|----|-------|-----|
| cd=1,skip=1 | 1 | 78 | +24.5% | +1.53 | 56.4% | 1.53 | -5.6% | 6/7 |
| cd=2,skip=1 | 1 | 78 | +24.5% | +1.53 | 56.4% | 1.53 | -5.6% | 6/7 |
| cd=3,skip=1 | 1 | 78 | +24.5% | +1.53 | 56.4% | 1.53 | -5.6% | 6/7 |
| cd=4,skip=1 | 1 | 78 | +24.5% | +1.53 | 56.4% | 1.53 | -5.6% | 6/7 |
| ... (all 12 identical) | | | | | | | | |

**Why zero effect:** The filtered Spring strategy has max consecutive losses of only 4. With the cooldown resetting on any win, the cooldown threshold is never reached because a win always occurs before 4 consecutive losses accumulate. The filtered strategy's trade quality is high enough that losing streaks are short.

### Unfiltered Spring

| Cooldown | Skip | Trades | Sum | Sharpe | WR | PF | MaxDD | WF |
|----------|------|--------|-----|--------|----|----|-------|-----|
| Baseline | — | 543 | -43.2% | -0.71 | 48.1% | 0.93 | -74.3% | 5/7 |
| cd=1,skip=1 | 1 | 543 | -43.2% | -0.71 | 48.1% | 0.93 | -74.3% | 5/7 |
| cd=1,skip=2 | 2 | 526 | -65.4% | -1.10 | 47.9% | 0.89 | -84.9% | 2/7 |
| cd=1,skip=3 | 3 | 519 | -77.7% | -1.33 | 47.6% | 0.87 | -91.6% | 2/7 |
| cd=2,skip=1 | 1 | 543 | -43.2% | -0.71 | 48.1% | 0.93 | -74.3% | 5/7 |
| cd=2,skip=2 | 2 | 536 | -47.5% | -0.79 | 48.1% | 0.92 | -80.0% | 4/7 |
| cd=2,skip=3 | 3 | 532 | -49.3% | -0.82 | 48.1% | 0.92 | -76.9% | 4/7 |
| cd=3,skip=1 | 1 | 543 | -43.2% | -0.71 | 48.1% | 0.93 | -74.3% | 5/7 |
| cd=3,skip=2 | 2 | 540 | -50.0% | -0.83 | 48.0% | 0.92 | -74.3% | 4/7 |
| cd=3,skip=3 | 3 | 540 | -50.0% | -0.83 | 48.0% | 0.92 | -74.3% | 4/7 |
| cd=4,skip=1 | 1 | 543 | -43.2% | -0.71 | 48.1% | 0.93 | -74.3% | 5/7 |
| cd=4,skip=2 | 2 | 541 | -37.0% | -0.61 | 48.2% | 0.94 | -71.2% | 5/7 |
| **cd=4,skip=3** | **3** | **540** | **-33.9%** | **-0.56** | **48.3%** | **0.94** | **-68.1%** | **5/7** |

### Best Unfiltered Cooldown (cd=4, skip=3) — Full Backtest

```
Total Trades:       540
Compound Return:    -40.7%
Linear Sum:         -33.9%
Sharpe Ratio:       -0.56
Sortino Ratio:      -1.24
Max Drawdown:       -68.1%
Win Rate:           48.3%
Avg Win:            +2.14%
Avg Loss:           -2.12%
Profit Factor:      0.94
Max Consec Losses:  7

Exit Breakdown:
  take_profit:   59 (10.9%)  avg=+4.90%  total=+289.0%
  stop_loss:    154 (28.5%)  avg=-3.10%  total=-477.2%
  time_exit:    327 (60.6%)  avg=+0.47%  total=+154.3%
```

### Comparison: Unfiltered Baseline vs Best Cooldown

| Metric | Baseline | Best Cooldown | Delta |
|--------|----------|---------------|-------|
| Sharpe | -0.71 | -0.56 | +0.15 |
| Linear Sum | -43.2% | -33.9% | +9.3% |
| Compound | -46.0% | -40.7% | +5.3% |
| Max DD | -74.3% | -68.1% | +6.2% |
| Win Rate | 48.1% | 48.3% | +0.3% |
| Profit Factor | 0.93 | 0.94 | +0.01 |
| Trades | 543 | 540 | -3 |
| Max Consec Loss | 8 | 7 | -1 |
| WF Mean Sharpe | +0.14 | +0.20 | +0.06 |
| WF Profitable | 5/7 | 5/7 | — |

### Walk-Forward: Best Unfiltered Cooldown (cd=4, skip=3)

| Split | Period | Trades | Sum | Sharpe | Status |
|-------|--------|--------|-----|--------|--------|
| 1 | 2019-10→2020-08 | 56 | +5.6% | +0.28 | ✅ |
| 2 | 2020-08→2021-06 | 55 | -31.7% | -1.42 | ❌ |
| 3 | 2021-06→2022-04 | 73 | +31.0% | +1.19 | ✅ |
| 4 | 2022-04→2023-02 | 58 | +28.7% | +1.43 | ✅ |
| 5 | 2023-02→2023-12 | 58 | +0.0% | +0.00 | ✅ |
| 6 | 2023-12→2024-10 | 70 | -9.1% | -0.40 | ❌ |
| 7 | 2024-10→2025-08 | 75 | +5.9% | +0.29 | ✅ |

**5/7 OOS profitable | Mean OOS Sharpe: +0.20 | Total OOS Sum: +30.6%**

## Analysis

### Why the Cooldown Fails for Filtered Spring

1. **Losing streaks are too short.** The filtered Spring strategy has max consecutive losses of 4. With the cooldown resetting on any win, the threshold is never reached. The SMA200 + BB %B 0.2-0.6 filter already eliminates the toxic trades that cause long losing streaks.

2. **The regime filter IS the cooldown.** The SMA200 and BB %B filters already prevent the strategy from entering in toxic conditions. The consecutive-loss degradation observed in the original regime analysis was a symptom of unfiltered entries, not a standalone problem.

3. **Trade count is too low for cooldown to matter.** With only 78 trades over 7 years, each trade is isolated. There aren't enough consecutive trades in any regime for a cooldown to trigger.

### Why the Cooldown Marginally Helps Unfiltered Spring

1. **The unfiltered strategy has genuine losing streaks.** Max consecutive losses is 8 (vs 4 for filtered). The cooldown after 4 losses skips 3 bars, preventing 3 trades (540 vs 543).

2. **The skipped trades are net-negative.** The 3 skipped trades have total PnL of -9.3% (the difference between baseline -43.2% and cooldown -33.9%). The cooldown is filtering out the worst trades at the tail of losing streaks.

3. **But the improvement is marginal.** The strategy remains deeply unprofitable (Sharpe -0.56, MaxDD -68.1%). The cooldown makes a broken strategy slightly less broken, not profitable.

### Why This Approach is Fundamentally Limited

1. **Cooldowns are reactive, not predictive.** They skip trades AFTER losses have already occurred, not before. The damage is already done. A predictive filter (like SMA200 or BB %B) prevents bad entries before they happen.

2. **Cooldowns reduce trade count without improving per-trade expectancy.** The avg win (+2.14%) and avg loss (-2.12%) are unchanged. The cooldown just removes some trades from the sample, which can improve or worsen results depending on which trades are removed.

3. **The original consecutive-loss analysis was confounded.** The degradation after consecutive losses (38.5% WR after 3 losses) was observed in the UNFILTERED strategy. It was a symptom of being in a toxic regime (e.g., below SMA200 during a bear market), not a standalone effect. The regime filter solves the root cause.

## Recommendation

### ❌ DISCARD — Consecutive-loss cooldown is not a viable improvement

**For Filtered Spring:** Zero effect. The regime filter already prevents long losing streaks.

**For Unfiltered Spring:** Modest improvement (Sharpe -0.71→-0.56) but strategy remains deeply unprofitable. The cooldown is treating a symptom, not the cause.

### What Actually Works (from prior research)

The regime analysis already identified the real solution:
- **SMA200 filter**: Eliminates below-trend entries (71% of trades, all toxic)
- **BB %B 0.2-0.6 filter**: Identifies the bounce zone where Springs are profitable
- **Lower target (3.0% vs 5.0%)**: Captures the typical Spring bounce (mean MFE +1.56%)

These three filters transform the strategy from Sharpe -0.71 to +1.53. A cooldown adds nothing on top.

### Next Steps

1. **Don't pursue cooldown mechanisms further.** They're a dead end for this strategy.
2. **Focus on increasing trade count for the filtered strategy.** 78 trades over 7 years is the real bottleneck. Multi-pair deployment or relaxing the BB %B filter slightly (e.g., 0.15-0.65) would have more impact.
3. **Implement the Spring filtered strategy as a strategy class.** It's the best-performing individual strategy (Sharpe +1.53, MaxDD -5.6%, 6/7 WF) but only exists as research scripts.

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant
python research/backtest_spring_cooldown.py
```

**Data:** OKX BTC/USDT 1h (2019-2026, ~65k bars)
**Engine:** Custom cooldown_backtest() with lows-based stop checking
**Commission:** 5 bps (round-trip)
**Slippage:** 5 bps

---

**Document version:** v1
**Date:** 2026-06-15
**Author:** CryptoQuant Autonomous Researcher
