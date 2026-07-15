# ATRBreakoutTrend — SL/TP Study (2026-07-08)

> ## ⛔ 基线作废（审计于 2026-07-15）· 策略已移除
>
> **本文所有数字产自 2026-07-13 引擎语义修复之前，已全部作废。**
> 那次修复（`02c308a`）修掉了两处偏差：signal 离场按当根开盘成交（**离场
> 前视**，每次离场凭空避开一根 bar 的不利行情）、以及持仓型策略 1→0
> **从不平仓**。修复当天只重校了 `DogeDonchianTrend`，本策略被漏掉，此后
> 近两天里它一直是 `config.yaml` 的默认策略。
>
> 2026-07-15 实测，同一段数据（OKX BTC/USDT 5m，105,120 根）、同样成本
> （10 bps 手续费 + 1 bps 滑点/边）、**只切换引擎版本**：
>
> | 引擎 | 收益 | Sharpe | MaxDD | PF |
> |---|---:|---:|---:|---:|
> | 修复前（`0c492a7`） | +57.2% | 1.34 | 22.9% | 1.15 |
> | **修复后（当前）** | **-90.6%** | **-5.10** | **91.3%** | **0.59** |
>
> 即：本策略的全部「优势」都是引擎缺陷造出来的。另外它的 `generate_signal()`
> 输出即持仓，却未设 `signal_is_position`（通道出场在回测里从不执行）；
> 打开该标志后更差（-98.4%）—— 问题不止于此。
>
> **未解释的差异**：上述实测为 1020 笔，本文基线称 430 笔。数据窗口仅差 2 天，
> 不足以解释；若日后要复活本族，这是第一个要查的地方。
>
> **2026-07-15：`strategies/atr_breakout_trend.py` 与其测试已从仓库移除**，
> `config.yaml` 的 `trading.strategy` 一并置空。下方 SL/TP 结论（"never add a
> percent stop-loss below 3%"）建立在作废基线之上，同样不可引用。
>
> 连带影响：`new_strategy_scan_2026-07-08.md` 整份扫描以本策略为基准
> （六个候选族都是输给它才被否决的），那些否决结论需重新审视。
>
> 本文保留作为反证记录。

**Verdict (作废): keep `stop_loss_pct: null` and `take_profit_pct: null` in config.**

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
