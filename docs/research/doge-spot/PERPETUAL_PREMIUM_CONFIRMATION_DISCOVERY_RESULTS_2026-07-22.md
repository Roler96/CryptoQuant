# DOGE 永续溢价趋势确认发现结果 (2021-2023)

> spot 与 swap 查询均硬截止 2024-01-01; 未读取后续年度。

## 结论

**DISCOVERY FAIL**

## 冻结主版本

| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| -17.86% | -0.40 | -41.14% | 117 | -0.13% | -38.79% | -22.52% | -46.62% |

## 冷启动自然年

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | +15.14% | 0.77 | -17.42% | 35 |
| 2022 | -16.30% | -1.91 | -20.36% | 39 |
| 2023 | -14.76% | -2.14 | -19.32% | 43 |

## 固定邻域与机制消融

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| history120 | +10.32% | 0.27 | -39.37% | 126 | +0.13% |
| history270 | -13.71% | -0.31 | -37.39% | 112 | -0.11% |
| entry05 | -15.21% | -0.24 | -46.86% | 203 | -0.06% |
| entry15 | -12.92% | -0.36 | -32.87% | 65 | -0.18% |
| momentum_only | +55.87% | 0.59 | -53.89% | 245 | +0.26% |
| premium_only | -21.67% | -0.44 | -43.83% | 151 | -0.13% |

## 匹配随机入场

- Observed episode return: `-17.86%`
- Random median: `+5.00%`
- Random P5-P95: `-26.43%` .. `+122.93%`
- Raw one-sided p: `0.861214`
- Sidak-adjusted p (5 tradable versions): `0.999949`

## 冻结门明细

- FAIL - 15 bps return > 0
- FAIL - 15 bps Sharpe >= 0.50
- FAIL - MaxDD <= 20%
- PASS - at least 12 closed trades
- FAIL - at least two positive cold-start years
- FAIL - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- FAIL - episode bootstrap P5 > 0
- FAIL - all four fixed structural neighbors profitable
- FAIL - joint state beats momentum-only Sharpe and MaxDD
- PASS - joint state beats premium-only Sharpe
- FAIL - year/holding matched random Sidak-adjusted p <= 0.10

## Provenance

- Spot 1h fingerprint: `b944b1f7186c18cd`
- Swap 1h fingerprint: `7bc7cda48685b2b8`
- Spot 4h fingerprint: `cd5e686612d9325d`
- Swap 4h fingerprint: `951fb3e7e290bb79`
- 4h bars: 6570
- Range: `2021-01-01..2023-12-31`
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed 4h decision, next open fill, 25% spot target
- Protocol: `PERPETUAL_PREMIUM_CONFIRMATION_PROTOCOL_2026-07-22.md`

按冻结规则, PPC v1 在 discovery 永久停止; 不读取 2024, 不挑邻域替补。
