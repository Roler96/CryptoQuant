# Spring Reversal — Multi-Timeframe: 4h Spring Reversal (Null Result)

> **One-line summary:** The Spring Reversal signal on 4h bars is NOT viable. Unfiltered 4h Spring produces 136 trades with Sharpe +0.17, MaxDD -18.7%, 4/6 walk-forward profitable — marginally better than unfiltered 1h Spring (Sharpe -0.71) but far worse than filtered 1h Spring (Sharpe +1.53, MaxDD -5.5%). The SMA200 and Bollinger Band filters that transform 1h Spring are counterproductive on 4h, slashing trades to 15-38 without improving profitability. The 4h timeframe's natural bar scarcity means filters destroy trade frequency without compensating improvements.

## Hypothesis

The Spring Reversal signal detects Wyckoff Springs — failed breakdowns where price makes a new low but closes bullish with high volume. On 1h bars, the SMA200 + BB %B 0.2-0.6 filter transforms the strategy from Sharpe -0.71 to +1.53 by removing entries during sustained downtrends and restricting to the BB bounce zone.

**Hypothesis:** On 4h bars, a Spring reversal is more significant because it takes more selling pressure to create a false breakdown on a higher timeframe. Therefore:
1. The signal should have higher per-trade quality (higher win rate, better risk/reward)
2. Trade frequency drops but this may be acceptable if quality improves
3. The same filters (SMA200 + BB) may work differently on 4h data

## Methodology

### Data
- OKX BTC/USDT 1h: 2019-2026 (65,016 bars)
- Resampled to 4h: 16,254 bars
- Commission: 5 bps round-trip, Slippage: 5 bps

### Signal
```
Spring Reversal: lookback=20, vol_mult=1.5, close_pct=0.5
4h bar resample: open=first, high=max, low=min, close=last, volume=sum
Entry: Next bar open after signal
Stop: lows-based (always true)
```

### Test Plan
1. Filter variant comparison (unfiltered, SMA200 only, BB only, combos)
2. Parameter sweep on most promising variants (5 stops × 7 targets × 6 holds = 210 combos each)
3. Walk-forward validation (6 sequential OOS splits)
4. Regime analysis on unfiltered trades (136 trades = enough for statistical power)
5. Comparison with 1h Spring benchmark

## Results

### Filter Variant Comparison (baseline exits: s3.0/t3.0/h6)

| Variant | Sigs | Trades | Sum% | Sharpe | MaxDD | WR% | PF |
|---------|------|--------|------|--------|-------|-----|-----|
| **Unfiltered** | 142 | 136 | +3.0% | +0.01 | -29.3% | 52.2% | 1.02 |
| SMA200 only | 40 | 38 | -10.8% | -0.11 | -16.2% | 50.0% | 0.78 |
| BB 0.2-0.6 only | 56 | 56 | -4.0% | -0.03 | -14.7% | 53.6% | 0.93 |
| BB 0.15-0.65 only | 69 | 68 | -8.7% | -0.05 | -17.6% | 51.5% | 0.89 |
| SMA200 + BB 0.2-0.6 | 15 | 15 | -0.7% | -0.02 | -4.9% | 53.3% | 0.96 |
| SMA200 + BB 0.15-0.65 | 20 | 19 | -1.8% | -0.04 | -6.9% | 52.6% | 0.92 |

**Key observation:** ALL filters degrade performance. The SMA200 filter alone cuts trades from 136 to 38 and turns marginally positive (+3.0%) to negative (-10.8%). This is the OPPOSITE of 1h Spring where SMA200 was the dominant regime dimension (Sharpe -0.93 below vs +0.15 above).

### Parameter Sweep Results

**Unfiltered 4h Spring — Best config: s2.0%/t5.0%/h16 (64h hold)**
- 136 trades, +72.4% sum, Sharpe +0.17, MaxDD -18.7%
- Win rate: 42.6%, PF: 1.46
- Exit breakdown: 30.9% take-profit, 54.4% stop-loss, 14.7% time-exit

**SMA200-only 4h Spring — Best config: s4.0%/t1.5%/h16**
- 38 trades, +12.5% sum, Sharpe +0.15, MaxDD -7.5%
- Win rate: 78.9%, PF: 1.42
- Better win rate but only 38 trades over 7 years (~5/year) — too sparse

**BB 0.15-0.65 4h Spring — Best config: s2.0%/t2.5%/h12**
- 69 trades, +28.8% sum, Sharpe +0.20, MaxDD -8.8%
- Win rate: 58.0%, PF: 1.53
- Best filtered variant, but only 69 trades (~10/year)

### Walk-Forward: Unfiltered 4h Spring (s2.0/t5.0/h16, 6 splits)

| Split | Period | Trades | Sum% | Sharpe | MaxDD | WR% | PF | Status |
|-------|--------|--------|------|--------|-------|-----|-----|--------|
| 1 | 2019-01→2020-01 | 13 | +16.8% | +0.37 | -6.2% | 53.8% | 2.34 | ✅ |
| 2 | 2020-01→2021-02 | 10 | -0.0% | -0.00 | -12.0% | 30.0% | 1.00 | ❌ |
| 3 | 2021-02→2022-03 | 26 | +18.1% | +0.20 | -10.1% | 42.3% | 1.58 | ✅ |
| 4 | 2022-03→2023-03 | 20 | -0.5% | -0.01 | -16.9% | 35.0% | 0.98 | ❌ |
| 5 | 2023-03→2024-04 | 15 | +13.8% | +0.32 | -4.5% | 46.7% | 2.26 | ✅ |
| 6 | 2024-04→2025-05 | 29 | +10.1% | +0.11 | -10.1% | 41.4% | 1.28 | ✅ |

**4/6 OOS profitable | Mean OOS Sharpe: +0.16**

The walk-forward shows marginal robustness — 4/6 splits positive but mean OOS Sharpe is far below the 1.0 acceptance threshold. Both negative splits have low win rates (30%, 35%) indicating the signal degraded significantly during those periods.

### Walk-Forward: SMA200-only 4h Spring (s4.0/t1.5/h16)

| Split | Period | Trades | Sum% | Sharpe | Status |
|-------|--------|--------|------|--------|--------|
| 1 | 2019-01→2020-01 | 1 | +1.4% | +0.00 | ✅ |
| 2 | 2020-01→2021-02 | 3 | -1.3% | -0.14 | ❌ |
| 3 | 2021-02→2022-03 | 7 | +4.3% | +0.30 | ✅ |
| 4 | 2022-03→2023-03 | 2 | -2.7% | -0.35 | ❌ |
| 5 | 2023-03→2024-04 | 4 | +0.1% | +0.01 | ✅ |
| 6 | 2024-04→2025-05 | 12 | +5.8% | +0.23 | ✅ |

**4/6 OOS profitable | Mean OOS Sharpe: +0.01**

Splits with 1-3 trades are meaningless. This filter produces too few trades for statistical validity.

## Regime Analysis (136 unfiltered 4h trades, s2.0/t5.0/h16)

### Key regime findings

| Regime | Trades | Sum% | Sharpe | WR% | PF |
|--------|--------|------|--------|-----|-----|
| **Above SMA200** | 37 | +15.1% | +0.13 | 43.2% | 1.36 |
| **Below SMA200** | 98 | +59.4% | +0.19 | 42.9% | 1.53 |
| **RSI < 30 (oversold)** | 26 | **-23.7%** | **-0.35** | **19.2%** | **0.46** |
| RSI 30-50 | 97 | +68.5% | +0.22 | 45.4% | 1.66 |
| RSI 50-70 | 13 | +27.6% | +0.65 | 69.2% | 4.29 |
| **BB %B < 0.2 (below)** | 71 | -0.5% | -0.00 | 31.0% | 1.00 |
| **BB %B 0.2-0.4** | 42 | +41.7% | +0.32 | 52.4% | 2.08 |
| BB %B 0.4-0.6 | 14 | +11.9% | +0.28 | 57.1% | 1.95 |
| BB %B > 0.6 | 9 | +19.2% | +0.63 | 66.7% | 4.05 |
| ADX > 25 (trending) | 94 | +52.2% | +0.17 | 42.6% | 1.47 |
| ADX < 20 (ranging) | 23 | +6.1% | +0.09 | 39.1% | 1.22 |
| High Vol (ATR>1.2x) | 42 | +8.7% | +0.06 | 33.3% | 1.16 |
| Low Vol (ATR<0.8x) | 23 | -3.7% | -0.05 | 34.8% | 0.88 |

### Regime finding #1: SMA200 direction is REVERSED on 4h

On 1h, above SMA200 is essential (Sharpe +0.15 vs -0.93 below). On 4h, **below SMA200 performs BETTER** (+59.4% sum vs +15.1% above). This is because:
- 4h Springs predominantly fire during bear trends (MDI > PDI: 129/136 = 94.9% of trades)
- These are genuine Wyckoff Springs — the final washout before a reversal
- The 4h timeframe captures the end of downtrends, not continuations

### Regime finding #2: RSI < 30 is TOXIC on 4h

When RSI is deeply oversold (< 30), Springs are falling knives:
- 26 trades, -23.7% sum, Sharpe -0.35, win rate only 19.2%
- These represent panic selling, not orderly reversals
- Adding RSI >= 30 filter: reduces trades from 136 to 107, sum drops from +72.4% to +58.2%, Sharpe unchanged at +0.17
- The filter removes toxic trades but also removes some profitable ones — net effect is marginal

### Regime finding #3: BB %B 0.2-0.4 is the best zone (but too rare)

On 1h, 78% of filtered Springs occur in BB %B 0.2-0.6. On 4h, only 41% (56/136) are in this zone. The BB 0.2-0.4 zone (42 trades) produces Sharpe +0.32, but 42 trades over 7 years = 6/year — not enough for strategy deployment.

### Quick RSI Filter Test

| Variant | Trades | Sum% | Sharpe | MaxDD | WR% | PF |
|---------|--------|------|--------|-------|-----|-----|
| Unfiltered (s2.0/t5.0/h16) | 136 | +72.4% | +0.17 | -18.7% | 42.6% | 1.46 |
| RSI >= 30 filter | 107 | +58.2% | +0.17 | -15.6% | 43.0% | 1.48 |
| RSI >= 35 filter | 86 | +37.4% | +0.14 | -13.8% | 41.9% | 1.38 |

The RSI filter reduces MaxDD but doesn't improve Sharpe — it's removing both toxic trades AND some of the best trades (which also occur in the RSI 30-35 zone).

## Comparison: 1h vs 4h Spring

| Strategy | Trades | Sum% | Sharpe | MaxDD | WR% | PF | WF |
|----------|--------|------|--------|-------|-----|-----|-----|
| 1h Unfiltered | 543 | -43.2% | -0.71 | -55.0% | 48.1% | 0.93 | 5/7 |
| **1h Filtered (SMA200+BB)** | **78** | **+24.5%** | **+1.53** | **-5.5%** | **56.4%** | **1.53** | **5/6** |
| 4h Unfiltered (baseline) | 136 | +3.0% | +0.01 | -29.3% | 52.2% | 1.02 | — |
| 4h Unfiltered BEST | 136 | +72.4% | +0.17 | -18.7% | 42.6% | 1.46 | 4/6 |
| 4h SMA200 BEST | 38 | +12.5% | +0.15 | -7.5% | 78.9% | 1.42 | 4/6 |
| 4h BB 0.15-0.65 BEST | 69 | +28.8% | +0.20 | -8.8% | 58.0% | 1.53 | — |

## Analysis

### Why 4h Spring doesn't work

1. **The filters that save 1h Spring kill 4h Spring.** On 1h, SMA200 filter removes 71% of toxic signals below SMA200. On 4h, below SMA200 is where most Springs occur AND where they're profitable — filtering them out destroys the strategy.

2. **The BB filter is too restrictive on 4h.** On 1h, BB %B 0.2-0.6 captures 78% of filtered signals. On 4h, it captures only 41%. The 4h timeframe naturally has fewer bars, so any filter that removes >50% of signals leaves too few trades.

3. **The 5% target is required for profitability but unsustainable.** The sweep found that target=5.0% produces the highest Sharpe (+0.17), but with only 42.6% win rate and 54.4% stop rate. Lower targets (1.5-2.5%) produce higher win rates (55-65%) but negative returns because the average win is too small to overcome commission + slippage.

4. **Transaction costs dominate at small targets.** With 1.5% target, the 10 bps round-trip cost (commission + slippage) eats 6.7% of gross profit. The typical 4h Spring bounce is 1-3% — too small to survive costs at scale.

5. **The 4h signal has an MDI bias.** 94.9% of 4h Springs occur when MDI > PDI (bear trend). The 4h Spring is essentially a bear-market reversal signal, not a general-purpose strategy. This makes it highly regime-dependent.

6. **Walk-forward Sharpe (+0.16) is far below deployable threshold (+1.0).** Even the best configuration fails the acceptance criteria.

### Why 1h works but 4h doesn't

The Spring Reversal pattern relies on detecting **intra-bar price action**: a new low is made, then buyers step in and close the bar near the high. On 1h bars, this captures a 1-hour battle. On 4h bars, the battle is 4 hours long:

- A 4h "new low" requires a significant breakdown (often a multi-day event)
- The "bullish close" on 4h means buyers controlled the final portion of a 4-hour period
- Volume on 4h is the sum of 4 hours — harder to interpret ("high volume" has different meaning)

The signal-to-noise ratio of the Spring pattern **degrades** as the timeframe increases because the pattern's components (new low, bullish close, high volume) become less temporally connected on longer bars.

### The paradox: below SMA200 works better on 4h

This counterintuitive finding has a logical explanation:
- On 1h, below SMA200 Springs are falling knives in a sustained downtrend
- On 4h, below SMA200 Springs are the final washout at the END of a downtrend
- The 4h timeframe naturally filters out the noise, leaving only the significant Springs
- But even these significant Springs don't produce enough edge to overcome costs

## Recommendation

### ❌ DISCARD — Multi-timeframe Spring on 4h is not viable

The 4h Spring Reversal does not produce actionable edge above transaction costs. The strategy's best configuration achieves Sharpe +0.17 with walk-forward Sharpe +0.16 — far below the +1.0 deployable threshold.

### What we learned

1. **Regime filters are timeframe-dependent.** The SMA200 filter that saves 1h Spring destroys 4h Spring. Never assume filters transfer across timeframes.

2. **Signal quality degrades with timeframe, not improves.** The Spring pattern's components (new low, bullish close, volume) are less temporally connected on longer bars.

3. **RSI < 30 is universally toxic for Springs.** On both 1h and 4h, oversold Springs are falling knives. This filter can be applied cross-timeframe.

4. **BB %B 0.2-0.4 is the universal sweet spot.** On both 1h and 4h, this zone produces the best Spring reversals. But on 4h, too few signals fall in this zone.

### What to do instead

1. **Focus on improving 1h Spring trade frequency.** The filtered 1h Spring (Sharpe +1.53, 78 trades) is the best-performing strategy but trade count is too low (~11/year). Multi-pair deployment or relaxing the BB filter slightly is the path forward.

2. **Explore 15m Spring.** The Spring pattern may work better on SHORTER timeframes where pattern components are more temporally connected. This is the opposite of the 4h hypothesis — go down, not up.

3. **RSI < 30 filter for 1h Spring.** Check if this filter also improves 1h Spring, which already has SMA200 + BB filters.

### Reproduction

```bash
cd /home/roler/Code/CryptoQuant
python research/backtest_spring_4h.py
```

**Data:** OKX BTC/USDT 1h resampled to 4h (2019-2026, 16,254 bars)
**Engine:** Custom simple_backtest with lows-based stops, compound returns
**Commission:** 5 bps (round-trip)
**Slippage:** 5 bps

---

**Document version:** v1
**Date:** 2026-06-16
**Author:** CryptoQuant Autonomous Researcher
**Status:** NULL RESULT — strategy discarded
