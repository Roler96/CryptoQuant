# Spring Reversal — Vol Gate Entry Filter Research v1

> **One-line summary:** A volatility gate as a standalone entry filter FAILS for Spring Reversal (all variants have negative or near-zero Sharpe). However, combining the vol gate WITH the BB %B filter improves Sharpe by 63% (+0.48→+0.78) and WF robustness (4/7→5/7 profitable), at the cost of halving the already-low trade count (78→34). The BB filter is essential; the vol gate adds quality filtering on top.

## Hypothesis

The volatility gate was a breakthrough for Wick Inversion v4.5.0 (6/6 WF, mean OOS +1.26). The Spring Reversal regime analysis showed "Very High Vol (ATR ratio > 1.5)" is the single best vol regime for Spring (+0.76 Sharpe on unfiltered). However, previous Spring research only tested vol-adaptive EXITS (varying stop/target/hold based on vol), not a vol GATE as an entry signal filter.

**Hypothesis:** A volatility gate (ATR ratio > threshold) as an entry filter would either:
1. Replace the BB %B filter (preserving more trades while achieving similar quality), OR
2. Complement the BB filter (further improving quality at the cost of trade count)

## Methodology

### Data
- OKX BTC/USDT 1h: 2019-2026 (65,016 bars)
- Commission: 5 bps round-trip, Slippage: 5 bps
- Engine: Official `BacktestEngine` (daily equity curve Sharpe, lows-based stops, compound returns)

### Signal
```
Spring Reversal: lookback=20, vol_mult=1.5, close_pct=0.5
Entry: Next bar open after signal
Stop: lows-based (NOT closes-based)
```

### Filter Variants Tested
| Filter | Description |
|--------|-------------|
| No filters | Baseline Spring signal |
| SMA200 only | close > SMA(200) |
| SMA200 + BB [0.20, 0.60) | SMA200 + BB %B zone (current best) |
| SMA200 + VolGate > 0.7 | SMA200 + ATR ratio > 0.7 (above low vol) |
| SMA200 + VolGate > 1.0 | SMA200 + ATR ratio > 1.0 (above median) |
| SMA200 + VolGate > 1.5 | SMA200 + ATR ratio > 1.5 (very high vol) |
| SMA200 + BB [0.20,0.60) + VolGate > 1.0 | All three filters combined |
| SMA200 + BB [0.15,0.65) + VolGate > 1.0 | Expanded BB + vol gate |
| VolGate > 1.5 only | Vol gate without SMA200 or BB |

### Exit Parameter Grid
For the top 4 filters: 5 stops × 6 targets × 7 holds = 210 combinations each.
- Stops: 2.0%, 2.5%, 3.0%, 3.5%, 4.0%
- Targets: 1.5%, 2.0%, 2.5%, 3.0%, 3.5%, 4.0%
- Holds: 8, 10, 12, 14, 16, 20, 24 hours

### Validation
1. Full-period backtest (all 9 filter variants, fixed exits s3.0/t3.0/h16)
2. Exit parameter grid sweep (top 4 filters, 840 combos)
3. Full backtest with best configuration
4. 7-split walk-forward validation (best config, production config, vol-gate baseline)
5. Comparison with existing research baselines

## Results

### Experiment 1: Filter Comparison (s3.0/t3.0/h16)

| Filter | Trades | Return | Sharpe | MaxDD | WR | PF |
|--------|--------|--------|--------|-------|-----|-----|
| Baseline (no filters) | 585 | -71.9% | -0.51 | -57.8% | 49.9% | 0.87 |
| SMA200 only | 168 | -7.3% | -0.11 | -22.4% | 49.4% | 0.94 |
| **SMA200 + BB [0.20,0.60)** | **78** | **+21.0%** | **+0.48** | **-5.6%** | **52.6%** | **1.45** |
| SMA200 + VolGate > 0.7 | 147 | -16.1% | -0.26 | -26.0% | 49.0% | 0.87 |
| SMA200 + VolGate > 1.0 | 89 | -7.8% | -0.14 | -16.3% | 51.7% | 0.90 |
| SMA200 + VolGate > 1.5 | 20 | +3.5% | +0.13 | -7.2% | 50.0% | 1.22 |
| SMA200 + BB [0.20,0.60) + VolGate > 1.0 | 34 | +10.9% | +0.37 | -5.3% | 61.8% | 1.52 |
| SMA200 + BB [0.15,0.65) + VolGate > 1.0 | 41 | +5.0% | +0.15 | -6.1% | 56.1% | 1.18 |
| VolGate > 1.5 only (no SMA200) | 99 | +9.1% | +0.14 | -16.7% | 54.5% | 1.09 |

**Key finding:** The BB filter is irreplaceable for Spring. All vol-gate-only variants have negative or near-zero Sharpe. However, adding the vol gate ON TOP of the BB filter improves win rate (52.6%→61.8%) and profit factor (1.45→1.52) at the cost of trade count (78→34).

### Experiment 2: Exit Parameter Grid (Top 4 Filters)

| Filter | Stop | Target | Hold | Trades | Return | Sharpe | MaxDD | WR | PF |
|--------|------|--------|------|--------|--------|--------|-------|-----|-----|
| **SMA200 + BB [0.20,0.60) + VolGate > 1.0** | **3.0%** | **2.5%** | **24h** | **34** | **+25.7%** | **+0.78** | **-3.8%** | **73.5%** | **2.38** |
| SMA200 + BB [0.15,0.65) + VolGate > 1.0 | 3.0% | 2.5% | 24h | 41 | +22.0% | +0.61 | -4.4% | 68.3% | 1.84 |
| SMA200 + BB [0.20,0.60) | 3.5% | 3.0% | 16h | 78 | +19.7% | +0.44 | -6.9% | 52.6% | 1.41 |
| VolGate > 1.5 only | 3.5% | 2.5% | 20h | 98 | +20.6% | +0.32 | -16.5% | 59.2% | 1.21 |

### Experiment 3: Full Backtest — Best Configuration

```
Configuration: SMA200 + BB [0.20,0.60) + VolGate > 1.0
Exits: stop=3.0%, target=2.5%, hold=24h

Initial Capital:    10,000 USDT
Commission:         5 bps (round-trip)
Slippage:           5 bps

Total Trades:       34
Compound Return:    +28.3%
Linear Sum:         +25.7%
Sharpe Ratio:       +0.78
Sortino Ratio:      +0.16
Max Drawdown:       -3.8%
Win Rate:           73.5%
Avg Win:            +1.77%
Avg Loss:           -2.07%
Profit Factor:      2.38
Max Consec Losses:  2

Exit Breakdown:
  take_profit:   15 (44.1%)  avg=+2.40%  total=+36.0%
  stop_loss:      4 (11.8%)  avg=-3.10%  total=-12.4%
  time_exit:     15 (44.1%)  avg=+0.14%  total= +2.1%
```

**Comparison with BB-only baseline (78 trades):**
- Sharpe: +0.48 → +0.78 (+63%)
- MaxDD: -5.6% → -3.8% (-32%)
- Win Rate: 52.6% → 73.5% (+21pp)
- Profit Factor: 1.45 → 2.38 (+64%)
- Take-profit rate: 19.2% → 44.1% (+25pp)
- Stop-loss rate: 10.3% → 11.8% (slightly worse)
- Trades: 78 → 34 (-56%)

### Experiment 4: Walk-Forward Validation

#### Best Config: SMA200 + BB [0.20,0.60) + VolGate > 1.0, s3.0/t2.5/h24

| Split | Period | Trades | Return | Sharpe | DD | Status |
|-------|--------|--------|--------|--------|-----|--------|
| 1 | 2019-10→2020-08 | 6 | +7.0% | +1.69 | -1.6% | ✅ |
| 2 | 2020-08→2021-06 | 1 | -3.1% | -1.10 | -3.1% | ❌ |
| 3 | 2021-06→2022-04 | 3 | +1.7% | +0.41 | -3.1% | ✅ |
| 4 | 2022-04→2023-02 | 5 | +2.7% | +1.02 | -1.1% | ✅ |
| 5 | 2023-02→2023-12 | 5 | +7.1% | +1.81 | -0.9% | ✅ |
| 6 | 2023-12→2024-10 | 6 | +9.1% | +2.36 | -0.0% | ✅ |
| 7 | 2024-10→2025-08 | 3 | -0.6% | -0.17 | -3.1% | ❌ |

**→ 5/7 OOS profitable | Mean OOS Sharpe: +0.86 | Total OOS: +23.9%**

#### Production Config: SMA200 + BB [0.15,0.65), s3.0/t2.5/h24

| Split | Period | Trades | Return | Sharpe | Status |
|-------|--------|--------|--------|--------|--------|
| 1 | 2019-10→2020-08 | 12 | +13.7% | +2.06 | ✅ |
| 2 | 2020-08→2021-06 | 6 | -3.1% | -0.59 | ❌ |
| 3 | 2021-06→2022-04 | 11 | +1.7% | +0.26 | ✅ |
| 4 | 2022-04→2023-02 | 8 | -0.0% | -0.01 | ❌ |
| 5 | 2023-02→2023-12 | 14 | -1.9% | -0.29 | ❌ |
| 6 | 2023-12→2024-10 | 14 | +5.0% | +0.79 | ✅ |
| 7 | 2024-10→2025-08 | 16 | +4.1% | +0.65 | ✅ |

**→ 4/7 OOS profitable | Mean OOS Sharpe: +0.41 | Total OOS: +19.5%**

#### VolGate-only: SMA200 + VolGate > 1.0, s3.0/t3.0/h16

| Split | Period | Trades | Return | Sharpe | Status |
|-------|--------|--------|--------|--------|--------|
| 1 | 2019-10→2020-08 | 7 | +1.4% | +0.30 | ✅ |
| 2 | 2020-08→2021-06 | 12 | -10.8% | -1.19 | ❌ |
| 3 | 2021-06→2022-04 | 10 | +0.8% | +0.11 | ✅ |
| 4 | 2022-04→2023-02 | 9 | +5.1% | +1.39 | ✅ |
| 5 | 2023-02→2023-12 | 15 | +0.1% | +0.02 | ✅ |
| 6 | 2023-12→2024-10 | 16 | -0.6% | -0.08 | ❌ |
| 7 | 2024-10→2025-08 | 11 | -10.5% | -1.78 | ❌ |

**→ 4/7 OOS profitable | Mean OOS Sharpe: -0.17 | Total OOS: -14.6%**

### Experiment 5: Comparison Summary

| Configuration | Trades | Return | Sharpe | MaxDD | WR | PF |
|--------------|--------|--------|--------|-------|-----|-----|
| Baseline (no filters, s3/t3/h16) | 585 | -71.9% | -0.51 | -57.8% | 49.9% | 0.87 |
| SMA200 only (s3/t3/h16) | 168 | -7.3% | -0.11 | -22.4% | 49.4% | 0.94 |
| SMA200+BB[0.20,0.60) s3/t3/h16 | 78 | +21.0% | +0.48 | -5.6% | 52.6% | 1.45 |
| SMA200+BB[0.15,0.65) s3.0/t2.5/h24 (v1.1.0) | 91 | +19.4% | +0.37 | -8.5% | 56.0% | 1.28 |
| **SMA200+BB[0.20,0.60)+VolGate s3.0/t2.5/h24** | **34** | **+25.7%** | **+0.78** | **-3.8%** | **73.5%** | **2.38** |

## Analysis

### 1. The Vol Gate FAILS as a standalone Spring filter

This is the primary finding. Unlike Wick Inversion where the vol gate was transformational (6/6 WF, mean OOS +1.26), the vol gate cannot filter Spring signals effectively on its own:

- SMA200 + VolGate > 1.0: Sharpe -0.14, MaxDD -16.3% — worse than SMA200-only (-0.11, -22.4%)
- SMA200 + VolGate > 1.5: Sharpe +0.13, but only 20 trades over 7 years — statistically meaningless
- SMA200 + VolGate > 0.7: Sharpe -0.26, MaxDD -26.0% — actively toxic

**Why?** The vol-return relationship for Spring is non-monotonic:
- Very high vol (ATR ratio > 1.5): marginally positive (+0.13)
- High vol (1.2-1.5): toxic (-1.38 in regime analysis)
- Normal vol (0.8-1.2): slightly negative (-0.17)
- Low vol (<0.8): negative (-0.59 to -1.90)

A simple threshold like "> 1.0" mixes toxic and positive vol regimes. The BB %B filter, by contrast, targets a specific price-structure zone (%B 0.2-0.6) where Springs are genuine reversals, not falling knives.

### 2. BB + VolGate COMBO shows genuine improvement

The combination of BB %B 0.2-0.6 + VolGate > 1.0 delivers:
- **+63% Sharpe improvement** (+0.48 → +0.78)
- **-32% MaxDD reduction** (-5.6% → -3.8%)
- **+21pp Win Rate** (52.6% → 73.5%)
- **+64% Profit Factor** (1.45 → 2.38)
- **5/7 WF profitable** (vs 4/7 for production config)
- **Mean OOS Sharpe +0.86** (vs +0.41 for production config)

The mechanism: the BB filter identifies the structural Spring zone (near lower band in an uptrend). The vol gate then further filters: only take Springs where volatility is above normal, making the "failed breakdown" more meaningful. In low-vol environments, a "new low" is less dramatic and less likely to trap sellers.

### 3. Trade count collapse is the critical limitation

34 trades over 7.5 years = ~4.5 trades/year. Walk-forward splits have as few as 1 trade (split 2). This makes:
- Statistical significance questionable
- Live deployment impractical (months between trades)
- WF robustness assessment unreliable (1-trade split)

The production config (91 trades) and BB-only baseline (78 trades) are already sparse. Adding the vol gate halves an already-low count.

### 4. Production Spring config WF is weaker than expected

The v1.1.0 production config (SMA200 + BB [0.15, 0.65), s3.0/t2.5/h24) showed:
- Only 4/7 WF profitable
- Mean OOS Sharpe +0.41
- Negative splits: 2020-08→2021-06, 2022-04→2023-02, 2023-02→2023-12

This is worse than previously reported (6/7 WF on Binance with custom engine). Using the official BacktestEngine (daily equity curve Sharpe), the Spring strategy's WF robustness is marginal.

### 5. BB filter is ESSENTIAL — confirmed again

Without the BB filter, all configurations (SMA200-only, VolGate-only) are unprofitable. The BB filter is what makes Spring work — it isolates the specific price-structure zone where the "failed breakdown" is a genuine reversal, not a trend continuation.

### 6. Comparison with Wick v4.5.0

| Aspect | Wick v4.5.0 (Vol Gate) | Spring (Vol Gate) |
|--------|----------------------|-------------------|
| Vol gate alone works? | ✅ Sharpe +0.91, 6/6 WF | ❌ Sharpe -0.14 to +0.13 |
| Vol gate + other filters? | SMA200 optional | BB essential, vol gate additive |
| WF improvement | SMA200: 4/6 → Vol: 6/6 | BB: 4/7 → BB+Vol: 5/7 |
| Trade count impact | 2,574 → 1,097 (-57%) | 78 → 34 (-56%) |
| Mechanism | Vol gate removes low-vol false signals | BB identifies zone; vol gate refines quality |

The vol gate works for Wick because Wick is a momentum signal — high vol confirms momentum. Spring is a reversal signal — it needs the structural price zone (BB) first, and vol only adds incremental quality.

## Recommendation

### 🔬 MORE RESEARCH NEEDED — Vol gate is promising but trade count is too low

**What works:**
- BB + VolGate combo improves Sharpe by 63% and WF robustness (4/7→5/7)
- Win rate jumps from 52.6% to 73.5% with the vol gate
- The BB filter is irreplaceable — confirmed as essential for Spring

**What doesn't work:**
- Vol gate alone cannot replace the BB filter
- Vol gate as sole entry filter produces negative Sharpe
- The vol-return relationship for Spring is non-monotonic (not a simple threshold)

**What needs more work:**
1. **Multi-pair deployment is critical.** 34 trades/7yr on BTC is too sparse. Running on 10+ pairs could produce ~300+ trades/7yr, making the vol gate practical.
2. **Relax the vol threshold to increase trade count.** Test VolGate > 0.8 or > 0.9 to find the optimal balance between quality and quantity.
3. **Test vol gate on unfiltered Spring.** The regime analysis showed "Very High Vol" alone had Sharpe +0.76. Maybe a tight vol gate (>1.5) without SMA200 or BB could work — need more trades to verify.
4. **Spring needs the BB filter more than it needs the vol gate.** Prioritize BB filter in production; add vol gate only if multi-pair provides sufficient trade frequency.

### If deploying with vol gate today

```
Signal: Spring Reversal (lookback=20, vol_mult=1.5, close_pct=0.5)
Filters: close > SMA(200) AND BB %B in [0.20, 0.60) AND ATR ratio > 1.0
Stop: 3.0% (lows-based)
Target: 2.5%
Hold: 24 hours
Commission: 5 bps, Slippage: 5 bps
```

Expected: Sharpe ~+0.6-0.9, MaxDD ~-4%, ~5 trades/year on BTC.

## Reproduction

```bash
cd /home/roler/Code/CryptoQuant
uv run python research/backtest_spring_vol_gate.py
```

**Data:** OKX BTC/USDT 1h (2019-2026, 65,016 bars)
**Engine:** Official `BacktestEngine` (daily equity curve Sharpe, lows-based stops, compound returns)
**Commission:** 5 bps (round-trip)
**Slippage:** 5 bps

---

**Document version:** v1
**Date:** 2026-06-16
**Author:** CryptoQuant Autonomous Researcher
**Related:** docs/research/spring/research_regime_analysis_v1.md, docs/research/wick/research_vol_gate_target_v1.md
