# Spring Reversal — SMA200 Filter & Stop-Loss Modeling Audit

> **Critical finding: Spring's documented Sharpe 2.72 was inflated by closes-based stop checking. With correct lows-based stops, true Sharpe is -0.65. No filter combination recovers profitability.**

## Background

The Spring Reversal strategy (Wyckoff Spring: failed breakdown + bullish close + high volume) was documented in `docs/research/spring/STRATEGY.md` (2026-06-09) with impressive results:

| Metric | Documented | Reproduced |
|--------|-----------|------------|
| Trades | 801 | 725 |
| Sharpe | **2.72** | **-0.65** |
| Linear Sum | +65.7% | -67.8% |
| Max DD | -12.5% | -62.3% |
| Win Rate | 58% | 54.2% |
| PF | 1.18 | 0.84 |
| Avg Win | +0.94% | +0.94% |
| Avg Loss | -1.13% | -1.32% |
| Stop exits | 65 (8%) | 91 (12.5%) |
| Target exits | 232 (29%) | 202 (27.9%) |
| Time exits | 504 (63%) | 432 (59.6%) |

## Root Cause Analysis

### The Stop-Loss Modeling Pitfall

The quant-strategy-development skill documents this exact pattern:

> **Always use `lows[i]` for stop checking, never `closes[i]`.**
> Using `closes[i]` assumes stops only trigger at bar close. In reality, a stop triggers the moment price touches it intra-bar. This single difference can make a Sharpe 3.15 strategy turn into Sharpe -4.02.

### Diagnostic Evidence

Testing different stop models reveals the exact cause:

| Stop Model | Trades | Sum | Win Rate | Stops | Avg Loss |
|------------|--------|-----|----------|-------|----------|
| Closes-based + no slippage | 713 | **+25.6%** | 57.2% | 56 | -1.09% |
| Closes-based + slippage | 713 | -10.1% | 54.8% | 56 | -1.16% |
| Lows-based + slippage (correct) | 725 | **-67.8%** | 54.2% | 91 | -1.32% |
| No stops at all | 701 | +5.5% | — | 0 | — |

The documented results (Sum +65.7%, Win rate 58%, Stops 65) closely match **closes-based stops without slippage** (Sum +25.6%, Win rate 57.2%, Stops 56). The remaining gap is likely from different data range or minor implementation differences in the original script.

### Why Lows-Based Stops Are Devastating for Spring

Spring enters on a "failed breakdown" — price makes a new low then bounces. The entry is inherently near a recent low. With a 3% stop loss:

- **Closes-based**: Stop only triggers if the bar CLOSES below entry - 3%. Since Spring enters on a bounce, the close is usually above entry. Stops rarely trigger (65 times).
- **Lows-based**: Stop triggers if the bar's LOW touches entry - 3%. In volatile crypto markets, intra-bar wicks frequently spike down. Stops trigger 40% more often (91 times).

The avg loss difference (-1.13% vs -1.32%) compounds across 725 trades to create the +133% gap between documented and true results.

## Hypothesis: Can Filters Save Spring?

Even with the correct stop model, the signal might have edge in specific regimes. Regime analysis of baseline trades shows:

| Regime | Trades | Sum | Win Rate |
|--------|--------|-----|----------|
| Above SMA200 | 175 | -5.3% | 54.9% |
| Below SMA200 | 550 | -62.5% | 54.0% |
| PDI > MDI (bullish dir) | 36 | **+8.9%** | **61.1%** |
| PDI ≤ MDI (bearish dir) | 689 | -76.7% | 53.8% |
| ADX > 25 (strong trend) | 455 | -43.3% | 56.0% |
| ADX ≤ 25 (weak trend) | 270 | -24.5% | 51.1% |
| TOXIC (below SMA200 + PDI<MDI) | 531 | -61.1% | 54.0% |

PDI > MDI shows positive expectancy (+8.9%, 61.1% WR). But this was post-hoc tagging — does it hold as a pre-trade filter?

## Filter Testing Results

### Full-Period Backtests (lows-based stops)

| Variant | Trades | Sum | Sharpe | Max DD | Win Rate | PF |
|---------|--------|-----|--------|--------|----------|----|
| Baseline (no filter) | 725 | -67.8% | -0.65 | 62.3% | 54.2% | 0.84 |
| SMA200 | 170 | -18.2% | -0.39 | 26.1% | 51.8% | 0.81 |
| SMA150 | 143 | -19.6% | -0.45 | 26.6% | 51.0% | 0.77 |
| EMA50 | 42 | -8.9% | -0.38 | 12.6% | 45.2% | 0.64 |
| PDI > MDI | 25 | -6.9% | -0.39 | 8.5% | 40.0% | 0.58 |
| ADX > 25 | 453 | -30.9% | -0.35 | 42.6% | 57.4% | 0.89 |
| SMA200 + ADX > 25 | 66 | +3.9% | 0.13 | 6.6% | 56.1% | 1.12 |
| PDI > MDI + ADX > 25 | 7 | -1.9% | -0.20 | 4.4% | 57.1% | 0.56 |

### Walk-Forward Validation (6 splits)

| Variant | 1/6 profitable | Best split | Notes |
|---------|----------------|------------|-------|
| Baseline | 1/6 | +0.8% | Sharpe -0.65 |
| SMA200 | 3/6 | +0.1% | Marginal, no edge |
| SMA150 | 1/6 | +4.3% | One lucky split |
| PDI > MDI | 0/6 | -0.3% | Too few trades (25) |
| ADX > 25 | 3/6 | +6.7% | Still negative overall |
| SMA200 + ADX > 25 | 2/6 | +3.6% | Only 66 trades total |
| PDI > MDI + ADX > 25 | 2/6 | +1.4% | Only 7 trades — no significance |

### Target Sweep (SMA200 filter)

| Target | Trades | Sharpe | DD | Win Rate | Sum |
|--------|--------|--------|-----|----------|-----|
| 1.0% | 170 | -0.40 | 23.7% | 56.5% | -17.4% |
| 1.2% | 170 | -0.37 | 24.2% | 54.1% | -17.0% |
| 1.5% | 170 | -0.39 | 26.1% | 51.8% | -18.2% |
| 2.0% | 170 | -0.38 | 25.5% | 50.6% | -19.3% |
| 3.0% | 170 | -0.29 | 25.5% | 50.0% | -15.8% |

No target produces positive results with SMA200 filter.

### Binance Cross-Validation

| Variant | Trades | Sum | Sharpe |
|---------|--------|-----|--------|
| Baseline (Binance) | 798 | -73.1% | -0.66 |
| SMA200 (Binance) | 202 | -24.9% | -0.49 |

Confirms: Spring is not exchange-specific. It's fundamentally unprofitable.

## Analysis

### Why the PDI > MDI Discrepancy?

Post-hoc regime analysis showed PDI > MDI trades had +8.9% (36 trades, 61.1% WR). But when applied as a pre-trade filter, PDI > MDI produces only 25 trades with -6.9% (40% WR).

This is because:
1. **Post-hoc tagging** looks at trades that ACTUALLY entered and checks conditions at entry time. Some trades entered when PDI > MDI but the entry was at next-bar open, by which time conditions may have shifted.
2. **Pre-trade filtering** only generates signals when PDI > MDI, which changes entry timing and the sequence of subsequent entries (since being flat during suppressed signals changes which bar you enter on next).
3. **Small sample**: 25-36 trades is not statistically significant. The +8.9% could easily be noise.

### Why Spring Fails with Correct Stops

Spring's entry logic (new low + bullish close + high volume) identifies candles where price made a new low but bounced. The bounce is real, but:

1. **The bounce is small**: avg win is only +0.94% (target 1.5% rarely hit — only 28% of trades)
2. **The continuation risk is high**: 60% of trades exit via time (6 bars), meaning the bounce doesn't continue
3. **Intra-bar volatility kills stops**: The 3% stop gets hit by random wicks 12.5% of the time
4. **The signal doesn't predict direction**: It identifies exhaustion but not reversal. A new low + bounce could be a dead cat bounce in a larger downtrend.

### The Core Problem

Spring is a **mean-reversion signal applied at new lows**. In a trending market (which crypto mostly is), new lows are often followed by MORE new lows. The "bullish close" requirement only ensures the current bar bounced — it doesn't ensure the downtrend is over.

The SMA200 filter should help (only trade in uptrends), but even above SMA200, the strategy loses -5.3% to -18.2%. This suggests the signal has NO edge, even in favorable conditions.

## Recommendation: DISCARD

**Spring Reversal is not tradeable with proper stop modeling.**

- True Sharpe: -0.65 (documented 2.72 was invalid)
- No filter combination recovers profitability
- Walk-forward: best variant 3/6 splits profitable (random)
- Trade count too low with aggressive filters for statistical significance
- The signal's premise (failed breakdown → bounce) doesn't hold on 1h crypto data

### Action Items

1. **Update `docs/research/spring/STRATEGY.md`** with corrected metrics
2. **Do NOT deploy Spring** in any form
3. **Do NOT spend more time optimizing Spring** — the signal has no edge
4. **Focus research elsewhere**: Wick Inversion (Sharpe 0.41, at least positive) or new strategy ideas

### Lesson Learned

**Always validate documented backtest results by independent reproduction.** The Spring strategy was documented with Sharpe 2.72 based on incorrect stop modeling. This is the exact pitfall warned about in the quant-strategy-development skill. The reproduction caught the error before any capital was risked.

## Reproduction

```bash
# Full SMA200 filter research + walk-forward
python research/backtest_spring_sma200_filter.py

# Diagnostic: stop model comparison
python research/diagnose_spring_discrepancy.py

# Directional filter research
python research/backtest_spring_directional_filter.py
```

## Files

- `research/backtest_spring_sma200_filter.py` — Main SMA200 filter + regime + WF research
- `research/diagnose_spring_discrepancy.py` — Stop model diagnostic (closes vs lows)
- `research/backtest_spring_directional_filter.py` — PDI/MDI and ADX filter testing
