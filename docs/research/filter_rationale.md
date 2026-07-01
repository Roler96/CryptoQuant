# Strategy Filter Rationale

> Why each filter exists, what happens when you disable it, and the backtest
> evidence. This document is the single source of truth for filter decisions.
> **Never disable a filter without reading this first.**

Last updated: 2026-06-30

---

## SpringReversal (v1.3.0) — Wyckoff Spring

### Filter 1: SMA200 Trend Filter (`sma200_filter=True`)

**What it does:** Only enter long when `close > SMA(200)`.

**Why it exists:** Springs are reversal patterns. A Spring that fires below SMA200
is a counter-trend bounce in a bear market — it gets crushed by the prevailing
downtrend. Above SMA200, Springs occur in uptrend pullbacks where reversals
actually hold.

**Empirical evidence (OKX BTC/USDT 1h, 2019-2026):**

| Variant | Sharpe | MaxDD | Trades |
|---------|--------|-------|--------|
| Baseline (no filters) | -0.71 | -55.0% | 543 |
| SMA200 only | +0.15 | -21.1% | 156 |
| SMA200 removed in v1.3.0 (from full filtered) | -0.76 | N/A | N/A |

- 71% of unfiltered signals are below SMA200
- Below SMA200: Sharpe -0.93; Above SMA200: Sharpe +0.15
- Removing SMA200 from v1.3.0's filtered strategy drops Sharpe from +0.56 to -0.76

**When safe to disable:** NEVER. This is the single most important filter.
Without it, the strategy is deeply unprofitable.

---

### Filter 2: BB %B Zone Filter `[0.15, 0.60)` (`bb_filter=True`)

**What it does:** Only enter when Bollinger %B is in [0.15, 0.60).

**Why it exists:** Springs that occur near the BB lower band (low %B) are genuine
bounce signals. Springs that fire near the BB upper band (high %B) are late entries
into overextended rallies — the reversal has already happened and you're buying
the top of a bounce.

The tight bounds [0.15, 0.60) were arrived at through multiple rounds of
out-of-sample testing (v1.0.0 → v1.3.0).

**Empirical evidence (OKX BTC/USDT 1h, same period):**

| Variant | Sharpe | MaxDD | Trades |
|---------|--------|-------|--------|
| SMA200 only (no BB filter) | +0.15 | -21.1% | 156 |
| SMA200 + BB [0.2, 0.6) v1.0 | +1.53 | -5.5% | 78 |
| SMA200 + BB [0.12, 0.65) v1.2 | +1.38 | N/A | 99 |
| SMA200 + BB [0.15, 0.60) v1.3 | +0.56 (daily) | -7.4% | N/A |

- v1.2 expanded lower bound to 0.12: gained 15 trades but added marginal quality
- v1.3 tightened to [0.15, 0.60): improved MaxDD from 10.3% → 7.4% (-28%)
- The [0.12, 0.15) zone: 11 trades with only marginal profitability — removed

**When safe to disable:** Only for ablation studies. Never in production.

---

## WickInversion (v4.4.1) — Seller Exhaustion

### Filter 1: Volatility Gating (`vol_gate_enabled=True`)

**What it does:** Only enter when `ATR(14) > 200-bar median ATR`.

**Why it exists:** Wicks are only meaningful signals during volatile periods.
In low-vol chop, wicks are noise — the seller/buyer imbalance ratio is
meaningless when ranges are tiny. The ATR ratio filter ensures we only trade
when there's real conviction behind the wick.

**Empirical evidence (OKX BTC/USDT 1h, 2019-2026):**

| Variant | Sharpe | MaxDD | Trades |
|---------|--------|-------|--------|
| Baseline (no filters) | -0.19 | -60.6% | 2574 |
| Vol gate only | +0.38 | -40.5% | 1318 |
| SMA200 only | +0.01 | -51.0% | 1563 |
| Vol + SMA200 | +0.55 | -23.3% | 821 |

- Without vol gate: Sharpe -0.19 (essentially random)
- With vol gate only: Sharpe +0.38 (directionally positive)
- Vol gate alone removes 49% of trades but eliminates the toxic low-vol noise

**When safe to disable:** Only if running a short-biased variant (not implemented).
Never disable in standard deployment.

---

### Filter 2: SMA200 Trend Filter (`trend_filter_enabled=True`)

**What it does:** Only enter long when `close > SMA(200)`.

**Why it exists:** Same rationale as SpringReversal — wicks below SMA200 are
counter-trend and get steamrolled by the bear move. The empirical split is
even more dramatic for WickInversion.

**Empirical evidence:**

- Below SMA200: Sharpe -1.13
- Above SMA200: Sharpe +2.50
- The filter removes 39% of trades but they're almost entirely losers

**When safe to disable:** See vol gate note. When both are disabled,
baseline Sharpe is -0.19 with -60.6% MaxDD — the strategy collapses.

---

## General Principles

### Why Filters, Not ML

The markets we trade (crypto spot, 1h timeframe) have ~1500-2500 bars/year.
Machine learning on this sample size is overkill and prone to overfitting.
Explicit, testable filters with clear economic rationale are more robust.

### Filter Interaction Warning

Filters interact multiplicatively. Adding a third filter to a strategy that
already has two can reduce trades below the 30-trade minimum for statistical
significance. Each additional filter should be tested with ablation studies
(SMA200 only, BB only, both) before deployment.

### OOS Lockbox

As of 2026-06-30, data from 2024-06-01 to 2026-06-30 is reserved as a **true
holdout lockbox**. This data must NEVER be used for:
- Parameter optimization
- Filter-bound tuning
- Strategy selection
- Any form of training

It may ONLY be used for a single final evaluation after a strategy is frozen
for 3+ months. Use `--oos-lockbox` in `_runner.py` to run this evaluation.

---

## Filter Change Log

| Date | Strategy | Change | Reason |
|------|----------|--------|--------|
| 2026-06-30 | All | Documented filter rationale | Phase 1: research hygiene |
| v1.3.0 | Spring | BB tightened [0.12,0.65)→[0.15,0.60) | Removed marginal zone; improved MaxDD |
| v1.2.0 | Spring | BB expanded [0.15,0.60)→[0.12,0.65) | Added 27 trades; later found marginal |
| v4.4.0 | Wick | Added vol gate + SMA200 filter | Sharpe -0.19→+0.55 |
