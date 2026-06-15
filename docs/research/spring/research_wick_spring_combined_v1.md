# Wick + Spring Combined Signal — Failure Analysis

> **One-line summary:** Wick Inversion and Spring Reversal have near-zero signal overlap (0.1%) but combining them does NOT improve risk-adjusted returns. The Wick filtered signal dominates the combined strategy and its negative performance (Sharpe -0.35) drags down results. Combined is 2/7 walk-forward profitable.

## Hypothesis

Wick Inversion (momentum/continuation, works in uptrends) and Spring Reversal (reversal, works in pullbacks within uptrends) operate in different market regimes. Combining them with OR logic should:
1. Increase trade frequency (reduce dry spells)
2. Smooth out equity curve (low correlation = diversification benefit)
3. Potentially improve risk-adjusted returns

## Methodology

### Signals
- **Wick**: imbalance_window=6, imbalance_threshold=0.35 (optimized), price_lookback=6, price_floor=-0.5%
- **Spring**: lookback=20, vol_mult=1.5, close_pct=0.5
- **Combined (unfiltered)**: Wick OR Spring
- **Combined (filtered)**: (Wick AND close > SMA200) OR (Spring AND close > SMA200 AND BB %B in [0.2, 0.6))

### Exit Parameters
- Unfiltered: s3.0/t2.0/h16 (compromise between Wick and Spring optimal exits)
- Filtered: s2.5/t2.0/h14 (compromise between Wick filtered s2.0/t1.5/h12 and Spring filtered s3.0/t3.0/h16)

### Validation
- Full backtest on OKX + Binance
- 7-split walk-forward on both exchanges

## Results

### Signal Overlap Analysis

| Metric | Unfiltered | Filtered |
|--------|-----------|----------|
| Wick signals | 4,515 | 2,622 |
| Spring signals | 662 | 82 |
| Overlap | 7 | 2 |
| Overlap % | 0.1% | 0.1% |
| Combined | 5,170 | 2,702 |

**Key finding:** The strategies fire in completely different conditions. Near-zero overlap confirms they are orthogonal signal types.

### Full Backtest (OKX BTC/USDT 1h, 2019-2026)

| Strategy | Trades | Sum | Sharpe | MaxDD | WR | PF | WF |
|----------|--------|-----|--------|-------|-----|-----|-----|
| Wick (imb=0.35, no filter) | 1,532 | +44.4% | +0.78 | -34.0% | 55.4% | 1.05 | 5/6* |
| Spring (no filter) | 543 | -43.2% | -0.71 | -55.0% | 48.1% | 0.93 | 5/6* |
| **Combined (unfiltered)** | 1,804 | +27.5% | +0.36 | -46.7% | 54.5% | 1.02 | **4/7** |
| Wick filtered (SMA200) | 930 | -5.6% | -0.14 | -39.2% | 53.5% | 0.99 | 5/6* |
| Spring filtered (SMA200+BB) | 78 | +24.5% | +1.53 | -5.5% | 56.4% | 1.53 | 5/6* |
| **Combined filtered** | 920 | -17.3% | -0.35 | -47.9% | 50.3% | 0.97 | **2/7** |

\* From prior research (not re-computed in this run)

### Combined Filtered Exit Breakdown

```
Exit Breakdown (OKX):
  take_profit:  271 (29.5%)  avg=+1.90%  total=+514.6%
  stop_loss:    164 (17.8%)  avg=-2.60%  total=-426.2%
  time_exit:    485 (52.7%)  avg=-0.22%  total=-105.7%
```

### Walk-Forward — Combined Filtered (OKX)

| Split | Period | Trades | Sum | Sharpe | DD | Status |
|-------|--------|--------|-----|--------|-----|--------|
| 1 | 2019-10→2020-08 | 99 | +40.6% | +2.69 | -7.7% | ✅ |
| 2 | 2020-08→2021-06 | 92 | -8.9% | -0.49 | -20.1% | ❌ |
| 3 | 2021-06→2022-04 | 84 | -3.1% | -0.18 | -21.1% | ❌ |
| 4 | 2022-04→2023-02 | 105 | -12.2% | -0.73 | -25.1% | ❌ |
| 5 | 2023-02→2023-12 | 118 | +1.2% | +0.07 | -16.7% | ✅ |
| 6 | 2023-12→2024-10 | 104 | -2.9% | -0.17 | -18.0% | ❌ |
| 7 | 2024-10→2025-08 | 122 | -4.8% | -0.30 | -20.9% | ❌ |

**2/7 OOS profitable | Mean OOS Sharpe: +0.13 | Total OOS Sum: +9.9%**

### Walk-Forward — Combined Unfiltered (OKX)

| Split | Period | Trades | Sum | Sharpe | Status |
|-------|--------|--------|-----|--------|--------|
| 1 | 2019-10→2020-08 | 188 | +28.6% | +1.18 | ✅ |
| 2 | 2020-08→2021-06 | 179 | -9.7% | -0.34 | ❌ |
| 3 | 2021-06→2022-04 | 198 | +27.0% | +0.97 | ✅ |
| 4 | 2022-04→2023-02 | 226 | -15.1% | -0.56 | ❌ |
| 5 | 2023-02→2023-12 | 203 | +29.2% | +1.46 | ✅ |
| 6 | 2023-12→2024-10 | 205 | -13.4% | -0.52 | ❌ |
| 7 | 2024-10→2025-08 | 220 | +12.5% | +0.50 | ✅ |

**4/7 OOS profitable | Mean OOS Sharpe: +0.38**

### Binance Cross-Validation

| Strategy | Trades | Sum | Sharpe | MaxDD | WR | PF | WF |
|----------|--------|-----|--------|-------|-----|-----|-----|
| Wick filtered | 849 | -6.6% | -0.17 | -40.1% | 53.5% | 0.99 | 4/7 |
| Spring filtered | 86 | +37.2% | +2.34 | -5.4% | 60.5% | 1.85 | 6/7 |
| **Combined filtered** | 858 | -9.9% | -0.21 | -42.2% | 50.8% | 0.98 | **3/7** |

## Analysis

### Why Combining Fails

1. **Wick dominates the combined strategy.** 920 of 920 combined filtered trades are Wick entries. The Spring filtered signal contributes 0 additional trades because all 82 Spring filtered signals fire on bars where a position is already open from a Wick entry. The combined strategy is effectively just the Wick filtered strategy with suboptimal exit parameters.

2. **Wick filtered is net-negative with tight stops.** The Wick filtered strategy (SMA200, imb=0.35) with tight stops (2.0-2.5%) produces Sharpe -0.14 to -0.35. The prior research's post-hoc Sharpe +2.50 for SMA200-filtered Wick was computed with stop=3.0%, not the tight stops used here.

3. **No diversification benefit.** With near-zero overlap, combining should theoretically provide diversification. But in practice, the Wick signal fires so much more frequently (2,622 vs 82 filtered) that it completely overwhelms the Spring signal. The Spring trades never get a chance to execute.

4. **The Spring filtered signal is too rare.** Only 82 filtered signals in 7 years (~1/month). The signal quality is excellent (Sharpe +1.53-2.34) but the frequency is too low to contribute meaningfully to a combined strategy.

5. **Exit parameters are a compromise.** The combined strategy needs a single set of exit parameters, but Wick and Spring have different optimal exits (Wick: tight stop, low target; Spring: wider stop, higher target). The compromise parameters (s2.5/t2.0/h14) work for neither.

### What Would Need to Change for Combining to Work

1. **Multi-pair deployment.** Spring only fires ~1/month on BTC. On 10+ pairs, it would fire ~10/month — enough to contribute meaningfully.

2. **Independent position management.** Each signal type would need its own exit parameters. But the current backtest framework doesn't support position stacking.

3. **Signal优先级.** Spring signals should take priority over Wick signals when they fire, since Spring has higher per-trade expectancy. But the current backtest only allows one position at a time.

### Comparison with Individual Strategies

| Metric | Wick (imb=0.35) | Spring Filtered | Combined Filtered |
|--------|-----------------|-----------------|-------------------|
| Sharpe | +0.78 | +1.53 | -0.35 |
| MaxDD | -34.0% | -5.5% | -47.9% |
| WF Profitable | 5/6* | 5/6* | 2/7 |
| Trades | 1,532 | 78 | 920 |

The Spring filtered strategy is the clear winner on a per-trade basis. The Wick strategy has more trades but lower quality. Combining them produces the worst of both worlds — Wick's low quality dominates and Spring's high quality is drowned out.

## Recommendation

### ❌ DISCARD — Do not combine Wick and Spring

**Rationale:**
- Combined filtered: Sharpe -0.35, 2/7 WF profitable — worse than either individual strategy
- Wick dominates the combined strategy (920/920 trades) and its negative performance drags down results
- Near-zero overlap (0.1%) means no diversification benefit in practice
- Exit parameter compromise hurts both strategies

### ✅ Instead, deploy Spring filtered independently

The Spring filtered strategy (SMA200 + BB 0.2-0.6) is the best-performing individual strategy:
- Sharpe +1.53, MaxDD -5.5%, 5/6 WF profitable
- Low trade count (78/7yrs) is the main limitation — address with multi-pair deployment

### 🔬 Wick needs further research

The Wick strategy with SMA200 filter and optimized exits needs re-evaluation with proper exit parameters (s3.0/t1.5/h12, not the tight stops tested here). The prior research's post-hoc Sharpe +2.50 may be achievable with the right exits.

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant
python research/backtest_wick_spring_combined.py
```

---

**Document version:** v1
**Date:** 2026-06-15
**Author:** CryptoQuant Autonomous Researcher
