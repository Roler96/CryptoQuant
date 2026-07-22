# DOGE 波动率管理现货发现结果 (2021-2023)

> 查询在数据库层硬截止 2024-01-01。VMS 永远做多、只按逆波动率调整仓位, 因此
> 匹配随机入场零假设不适用; 主检验改为对 buy-and-hold 的 Sharpe 差。
> 所有对比在共同 post-warmup 窗口 (bar index >= 386) 上进行。

**DISCOVERY FAIL**

## 候选对照 (共同窗口, 15 bps/边)

| Candidate | Return | Sharpe | MaxDD | Avg exp | Turnover |
|---|---:|---:|---:|---:|---:|
| vms | -12.54% | 0.26 | -60.31% | 89% | 8.5x |
| rv10 | -3.13% | 0.33 | -60.60% | 87% | 19.0x |
| rv40 | -9.08% | 0.31 | -60.76% | 92% | 4.7x |
| med365 | -16.97% | 0.26 | -65.05% | 92% | 7.3x |
| anti | -40.94% | 0.07 | -67.26% | 85% | 13.9x |
| buy_and_hold | -36.92% | 0.16 | -69.35% | 100% | 0.0x |

## 成本敏感度 (主策略, 共同窗口)

| Cost/side | Return | Sharpe |
|---|---:|---:|
| gross (0 bps) | -11.44% | 0.27 |
| 15 bps | -12.54% | 0.26 |
| 25 bps | -13.27% | 0.26 |

## Sharpe 差检验 (VMS - buy_and_hold, 联合 block bootstrap)

- Observed Sharpe: VMS `0.264` vs BH `0.160` → diff `+0.104`
- Bootstrap diff P5-P95: `-0.211` .. `+0.392` (median `+0.086`)
- 单侧 p(Sharpe_VMS <= Sharpe_BH): `0.317168`
- Sidak-adjusted p (trials=49): `1.000000`
- VMS deflated Sharpe (per-bar, trials=49): `0.0287`

## 逐年冷启动对照 (VMS vs buy_and_hold)

| Year | VMS Ret | VMS Sharpe | VMS MaxDD | BH Ret | BH Sharpe | BH MaxDD | VMS>BH |
|---:|---:|---:|---:|---:|---:|---:|:--:|
| 2021 | +2.95% | 0.38 | -53.03% | +2890.71% | 1.75 | -77.20% | N |
| 2022 | -41.81% | -0.21 | -62.86% | -58.86% | -0.32 | -71.32% | Y |
| 2023 | +24.63% | 0.67 | -36.59% | +27.28% | 0.70 | -39.76% | N |

## 发现门明细

- FAIL - 15 bps return > 0
- PASS - Sharpe beats buy-and-hold
- PASS - MaxDD below buy-and-hold
- FAIL - 25 bps/side return > 0
- PASS - Sharpe beats the anti-vol placebo
- FAIL - joint block-bootstrap one-sided p < 0.10
- FAIL - Sharpe beats buy-and-hold in at least two cold-start years

## Provenance

- Source fingerprint (1h): `b944b1f7186c18cd`
- Aggregated fingerprint (1d): `90ece55e00daf3d7`
- Bars (1d): 1095; common window start index: 386
- Range: `2021-01-01..2023-12-31`
- Query hard end: `2024-01-01 00:00 UTC` (exclusive)
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress; 5% weight quantization
- Execution: closed 1d decision, next 1d open fill, ON_ENTRY, long-only weight in [0, 1]
- Registered attempts (cumulative): 49
- Note: 2021 cold-year is partial for VMS (its 201-bar warmup consumes the first months); 2022-2023 are full.
