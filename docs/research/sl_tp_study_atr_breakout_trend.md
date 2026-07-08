# ATRBreakoutTrend — SL/TP Study (2026-07-08)

**Verdict: keep `stop_loss_pct: null` and `take_profit_pct: null` in config.**

Data: OKX BTC/USDT 5m, 365 days (2025-07-08 → 2026-07-08), 105,120 bars, zero gaps.
Engine: commission 5bps, slippage 5bps, full-equity compounding.

## Stop loss: catastrophic at any tested level

Grid over SL ∈ {1.0, 1.5, 2.0, 3.0}% on the 120d window (IS/OOS 80/20):

| SL | IS Sharpe | OOS Sharpe |
|----|-----------|------------|
| none | 4.21 | 7.62 |
| 3.0% | 3.71 | 3.98 |
| 2.0% | 3.92 | 3.63 |
| 1.5% | 2.13 | 3.74 |
| 1.0% | 0.59 | -1.47 |

The strategy holds ~22h on a 5m timeframe; intrabar noise routinely exceeds
1–2%. Tight stops convert winners into losers (SL 1% → 300 trades IS,
-18% return). Channel-exit is the strategy's own stop — it needs the room.

**Never add a percent stop-loss below 3% to this strategy.**

## Take profit: regime-dependent, rejected

On the recent 120d window TP looked great (TP 1.0–2.0 beat baseline on both
IS and OOS, broad plateau, e.g. TP1.5: IS Sharpe 5.36 vs 4.21). But the full
year shows the edge is not robust:

| TP | Sharpe | Return | MaxDD | PF |
|----|--------|--------|-------|-----|
| 1.0% | 3.35 | 308% | 25.8% | 1.32 |
| 1.5% | 3.39 | 299% | 23.5% | 1.35 |
| none | 3.23 | 233% | **16.0%** | **1.65** |

Walk-forward (5 × ~2-month folds), TP1.5 vs none: TP loses folds 1 and 3
(2025-09→11: 1.22 vs 2.29; 2026-01→03: 2.69 vs 3.77), wins folds 4–5 (the
window that made the 120d grid look good). Marginal Sharpe gain, materially
worse drawdown and profit factor → rejected. Re-evaluate only if a regime
detector can gate it.

## Baseline (1 year, no SL/TP)

Sharpe 3.23, return 233% (full compounding), MaxDD 16.0%, 430 trades,
win rate 38.8%, PF 1.65.

Scripts: session scratchpad `sl_tp_grid.py`, `tp_probe.py`, `tp_1y.py`
(grid logic trivially reproducible with BacktestEngine stop/tp params).
