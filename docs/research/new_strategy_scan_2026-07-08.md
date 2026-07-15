# New Strategy Family Scan (2026-07-08)

> ## ⚠️ 基准已作废（审计于 2026-07-15）
>
> 本文的判据是「打不过 ATRBreakoutTrend」，而**该基准本身已被推翻**：它的
> 数字产自 2026-07-13 引擎语义修复之前，修复后同一段数据实测为 **-90.6%
> / Sharpe -5.10**（详见 `sl_tp_study_atr_breakout_trend.md` 的批注）。
> 该策略已于 2026-07-15 从仓库移除。
>
> 因此第 1 条结论「Nothing beats the incumbent」**不再成立** —— 现役策略在
> 修正后的引擎上是净亏的，「输给它」不再是否决理由。
>
> 但这**不等于**六个候选族就此翻案。它们各自的绝对数字（IS/OOS Sharpe）同样
> 产自修复前引擎，方向未知：修复主要惩罚频繁离场的策略，而 5m 级别的候选族
> 大多如此。要复活其中任何一族，必须在修正后的引擎上重跑，不能引用本文数字。
>
> 保留有效的是**方法论结论**：不要在同一年数据上重刷网格（第 4 条），以及
> 「拒绝族登记表」作为「已试过什么」的记录 —— 但每一格的数字都要重测。

> Six candidate strategy families — none present in `strategies/` — were
> implemented and backtested against the production baseline. **Verdict (作废):
> no candidate beats ATRBreakoutTrend; all six are rejected for deployment.**
> This doc records what was tried so it is not re-tried from scratch.

**Data:** OKX BTC/USDT 5m, 2025-07-08 → 2026-07-08 (105,130 bars), plus a 1h
resample of the same window (8,762 bars).
**Costs:** real account fees — commission 10 bps/side + slippage 1 bps/side
(per-side engine semantics, post-9dc031e).
**Protocol:** IS = first 80%, OOS = last 20%. Round-2 grids scored on IS only;
one OOS evaluation per family for the IS-best config. Scan scripts in session
scratchpad: `new_strategy_scan.py`, `round2_filtered.py`, `round3_1h.py`.

## Baseline reference (same windows, same costs)

| ATRBreakoutTrend | Sharpe | Return | MaxDD | Trades | PF |
|---|---|---|---|---|---|
| 5m IS | 1.64 | 61.4% | 19.8% | 361 | 1.27 |
| 5m OOS | 3.12 | 21.8% | 6.6% | 73 | 1.66 |
| 1h IS | 2.32 | 92.5% | 8.0% | 43 | 2.94 |
| 1h OOS | 0.83 | 6.4% | 8.2% | 15 | 1.50 |

## Round 1 — raw signals, 5m

| Candidate | IS Sharpe | OOS Sharpe | Note |
|---|---|---|---|
| KeltnerSqueeze (TTM) | -2.70 | -3.49 | whipsaw death at 5m |
| VWAPZReversion | -3.25 | -2.24 | 56% win rate, PF 0.45 — tail losses |
| TSMomentum (2d lookback) | +0.69 | +0.04 | only non-negative raw signal |
| DonchianPullback (EMA re-cross) | -2.30 | -1.21 | pullback entries whipsaw |
| VolumeShock (vol z>3 continuation) | -0.48 | +2.07 | OOS-only fluke, see round 2 |
| OpeningRangeBreakout (UTC daily) | -0.31 | -2.19 | no session edge in crypto |

## Round 2 — proven filter playbook applied (trend gate + ATR vol gate), 5m

Coarse grids (12–18 configs/family) on IS only:

- **VolumeShock + vol gate:** best IS Sharpe 0.54 (z=3, exit EMA50, vol gate
  on). OOS: **0.05**. The round-1 OOS +2.07 was window luck, not edge.
- **TSMomentum:** best IS Sharpe 0.69 (lb=576, th=2%, no gate) — the untouched
  round-1 config; the grid found nothing better. OOS: **0.14**.
- **VWAPZReversion + trend gate:** trend gate and deep-dip entry are nearly
  mutually exclusive → 1–35 trades/config. Best config with ≥30 trades:
  IS Sharpe **-1.01**. Family dead on 5m.

## Round 3 — cost/noise hypothesis: same families at 1h

Rationale: 22 bps round trip is brutal at 5m; Spring/Wick live at 1h.

| Candidate (1h) | IS Sharpe | OOS Sharpe | Trades IS/OOS |
|---|---|---|---|
| KeltnerSqueeze | -0.17 | +0.87 | 95 / 19 |
| VWAPZReversion | -2.07 | -2.47 | 67 / 15 |
| TSMomentum (48h, 2%) | +1.18 | +0.40 | 85 / 23 |
| VolumeShock (z>3) | +1.51 | +0.79 | **17 / 8** |

## Conclusions

1. **Nothing beats the incumbent.** ATRBreakoutTrend dominates every candidate
   on both timeframes and both windows. The 2025-26 BTC regime rewards
   volatility-expansion trend following; the alpha families orthogonal to it
   (mean reversion, session structure, slow momentum) lose to costs or trend.
2. **VWAP mean reversion is decisively dead** on this market/period: negative
   in every configuration on both timeframes (12 configs). High win rate,
   catastrophic tails — reversion entries are trend entries on the wrong side.
3. **Two watchlist items, neither deployable:**
   - *TSMomentum 1h* (48h lookback, ±2%, zero-cross exit): positive both
     windows (1.18/0.40) but strictly dominated by the baseline and likely
     correlated with it (both long trends).
   - *VolumeShock 1h*: IS 1.51 / OOS 0.79 but 17+8 trades — below the
     30-trade significance floor. Re-examine only when more 1h history
     is available (needs multi-year data, not more parameters).
4. **Do not re-grid these families on this same year of data.** Any further
   tuning is in-sample mining. The productive next directions are new *data*
   (more symbols, longer history, funding/basis series), not new parameters.

## Rejected-family log

| Family | Status | Revisit condition |
|---|---|---|
| TTM Squeeze | rejected | different market (alt with vol clustering) |
| VWAP z-reversion | rejected | never on trend-regime BTC |
| Donchian/EMA pullback | rejected | — |
| UTC opening range | rejected | — |
| TS momentum | watchlist | as regime filter, not standalone |
| Volume shock | watchlist | ≥3y of 1h data for significance |
