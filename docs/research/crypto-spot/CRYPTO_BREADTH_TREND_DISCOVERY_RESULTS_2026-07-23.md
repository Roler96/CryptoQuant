# 加密市场广度确认 BTC 趋势发现结果 (CBT v1)

> 三市场查询均在数据库层排他硬截止 2025-06-01; 未读取验证窗。

## 结论

**DISCOVERY FAIL**

## 冻结主版本 (63d breadth + BTC SMA200, 15bps/边)

| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| +78.66% | 0.57 | -34.35% | 25 | +3.09% | +27.46% | +69.78% | -32.19% |

## 冷启动时段

| Period | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| 2021 | -20.80% | -0.52 | -27.20% | 6 |
| 2022 | +0.00% | 0.00 | -0.00% | 0 |
| 2023 | +37.61% | 1.04 | -29.38% | 7 |
| 2024 | +55.65% | 1.16 | -34.35% | 10 |
| 2025 YTD | +5.01% | 0.58 | -9.47% | 2 |

## 冻结邻域、消融与基准 (15bps/边)

| Version | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| momentum_fast | +76.74% | 0.58 | -35.11% | 31 |
| momentum_slow | +62.70% | 0.49 | -43.68% | 28 |
| trend_fast | +127.77% | 0.73 | -32.56% | 26 |
| trend_slow | +97.58% | 0.65 | -35.44% | 24 |
| btc_trend_only | +103.68% | 0.62 | -36.30% | 20 |
| breadth_only | +32.98% | 0.36 | -59.33% | 36 |
| buy_and_hold | +256.05% | 0.78 | -76.63% | 0 |

## 匹配随机入场

- Observed episode return: `+78.66%`
- Random median: `+163.34%`
- Random P5-P95: `-14.09%` .. `+711.51%`
- Raw one-sided p: `0.715828`
- Sidak-adjusted p (5 versions): `0.998147`

## 冻结门明细

- PASS — 15 bps return > 0
- FAIL — 15 bps Sharpe >= 0.75
- PASS — MaxDD <= 35%
- PASS — at least 8 closed trades
- PASS — at least 3 of 5 cold-start periods positive
- PASS — 25 bps/side return > 0
- PASS — return less best closed trade > 0
- FAIL — episode bootstrap P5 > 0
- PASS — all four fixed neighbors profitable
- PASS — MaxDD at least 25% below BTC buy-and-hold
- FAIL — breadth improves trend-only Sharpe without higher MaxDD
- PASS — trend filter improves breadth-only Sharpe
- FAIL — year/holding matched random Sidak-adjusted p <= 0.10

## Provenance

- Split fingerprint: `b0dc0b549c481d86`
- BTC 1h / 1d: `676dc430dc7dca30` / `c0306028b0681cda`
- ETH 1h / 1d: `ad0da6acddfad30d` / `79df71ca29ee5b05`
- DOGE 1h / 1d: `3414a877015d2b2d` / `333e3528e7e34948`
- Daily bars: 1612
- Range: `2021-01-01..2025-05-31`
- Query hard end: `2025-06-01 00:00 UTC` (exclusive)
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed UTC daily bar decision, next daily open fill, ON_ENTRY
- Registered tradable attempts: 5
- Protocol: `CRYPTO_BREADTH_TREND_PROTOCOL_2026-07-23.md`

按冻结规则, CBT v1 在 discovery 永久停止; 不读取验证窗、不从邻域替补、不修改参数。
