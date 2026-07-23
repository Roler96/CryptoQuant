# BTC 安静趋势发现结果 (BQT v1)

> BTC 查询在数据库层排他硬截止 2025-06-01; 未读取验证窗。

## 结论

**DISCOVERY FAIL**

## 冻结主版本 (90d momentum + 20d downside, 15bps/边)

| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| +6.30% | 0.18 | -54.83% | 27 | +0.81% | -26.73% | +0.62% | -53.98% |

## 冷启动时段

| Period | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| 2021 | -1.97% | 0.03 | -20.53% | 1 |
| 2022 | -27.55% | -1.87 | -27.55% | 5 |
| 2023 | -6.79% | -0.08 | -36.96% | 9 |
| 2024 | +66.38% | 1.81 | -20.00% | 10 |
| 2025 YTD | -3.48% | -0.30 | -12.65% | 2 |

## 冻结邻域、消融与基准 (15bps/边)

| Version | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| momentum_fast | +22.33% | 0.31 | -52.68% | 22 |
| momentum_slow | +27.28% | 0.35 | -37.34% | 21 |
| risk_fast | +44.11% | 0.46 | -42.92% | 28 |
| risk_slow | +77.05% | 0.62 | -39.19% | 22 |
| hysteresis_tight | +43.68% | 0.47 | -40.93% | 17 |
| hysteresis_loose | +31.15% | 0.36 | -51.84% | 28 |
| momentum_only | +57.79% | 0.46 | -57.96% | 34 |
| quiet_only | -62.86% | -0.43 | -80.83% | 20 |
| buy_and_hold | +256.05% | 0.78 | -76.63% | 0 |

## 匹配随机入场

- Observed episode return: `+6.30%`
- Random median: `+80.76%`
- Random P5-P95: `-27.17%` .. `+352.10%`
- Raw one-sided p: `0.827017`
- Sidak-adjusted p (7 versions): `0.999995`

## 冻结门明细

- PASS — 15 bps return > 0
- FAIL — 15 bps Sharpe >= 0.75
- FAIL — MaxDD <= 35%
- PASS — at least 8 closed trades
- FAIL — at least 3 of 5 cold-start periods positive
- PASS — 25 bps/side return > 0
- FAIL — return less best closed trade > 0
- FAIL — episode bootstrap P5 > 0
- PASS — at least 5 of 6 fixed neighbors profitable
- PASS — MaxDD at least 25% below BTC buy-and-hold
- FAIL — quiet risk improves momentum-only Sharpe without higher MaxDD
- PASS — momentum improves quiet-only Sharpe
- FAIL — year/holding matched random Sidak-adjusted p <= 0.10

## Provenance

- Split fingerprint: `772b2697e81014c1`
- BTC 1h fingerprint: `676dc430dc7dca30`
- BTC 1d fingerprint: `c0306028b0681cda`
- Daily bars: 1612
- Range: `2021-01-01..2025-05-31`
- Query hard end: `2025-06-01 00:00 UTC` (exclusive)
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed UTC daily bar decision, next daily open fill, ON_ENTRY
- Registered tradable attempts: 7
- Protocol: `BTC_QUIET_TREND_PROTOCOL_2026-07-23.md`

按冻结规则, BQT v1 在 discovery 永久停止; 不读取验证窗、不从邻域替补、不修改参数。
