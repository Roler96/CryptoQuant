# DOGE 周内季节性发现结果 (2021-2023)

> 查询在数据库层硬截止 2024-01-01; 2024/2025/2026 未读取。机制只依赖 UTC
> 星期几时钟, 不读取任何价格/动量/波动率/成交量/跨币/衍生品信息。

**DISCOVERY FAIL**

## 候选对照 (size=1.0, 15 bps/边)

| Candidate | Return | Sharpe | MaxDD | Trades | Less best 1 | Episodes |
|---|---:|---:|---:|---:|---:|---:|
| weekdays | +205.29% | 0.71 | -95.14% | 156 | -1795.50% | 156 |
| ex_mon | +910.68% | 0.83 | -81.35% | 156 | -1289.17% | 156 |
| ex_sun_only | +653.99% | 0.87 | -93.91% | 157 | -1921.47% | 157 |
| weekend_only | +101.99% | 0.63 | -43.39% | 156 | +10.10% | 157 |
| buy_and_hold | +1472.28% | 0.98 | -92.33% | 0 | +1472.28% | 1 |

## 主策略冷启动自然年

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | +976.16% | 1.43 | -76.70% | 51 |
| 2022 | -73.81% | -1.04 | -75.69% | 52 |
| 2023 | +8.46% | 0.42 | -38.39% | 52 |

## 成本敏感度 (主策略)

| Cost/side | Return | Sharpe |
|---|---:|---:|
| gross (0 bps) | +387.48% | 0.77 |
| 15 bps | +205.29% | 0.71 |
| 25 bps | +123.46% | 0.67 |

## 匹配随机入场 (主策略, trials=44)

- Observed: `+205.29%`
- Null median: `+224.73%`
- Null P5-P95: `-89.99%` .. `+22121.48%`
- Raw 单侧 p: `0.511049`
- Sidak-adjusted p: `1.000000`

## Pooled block bootstrap (主策略)

| Block episodes | P5 | Median | P95 |
|---:|---:|---:|---:|
| 2 | -94.85% | +150.08% | +38654.63% |
| 4 | -95.46% | +140.51% | +36835.78% |

## 逐年 jackknife (主策略)

| Removed year | Remaining episodes | Return |
|---:|---:|---:|
| 2021 | 104 | -71.59% |
| 2022 | 104 | +1065.50% |
| 2023 | 104 | +181.48% |

## 描述性季节性图 (仅解释, 不用于选择)

### UTC 星期几 1d 对数收益

| Weekday | Count | Mean | Std |
|---|---:|---:|---:|
| Mon | 156 | -0.765% | 7.218% |
| Tue | 156 | +0.011% | 6.458% |
| Wed | 156 | -0.067% | 7.265% |
| Thu | 156 | +1.178% | 14.637% |
| Fri | 156 | +0.659% | 7.471% |
| Sat | 157 | +0.578% | 8.391% |
| Sun | 157 | +0.169% | 5.408% |

### UTC 小时 1h 对数收益均值

| Hour | Count | Mean |
|---:|---:|---:|
| 00 | 1094 | -0.0145% |
| 01 | 1095 | +0.0509% |
| 02 | 1095 | -0.0131% |
| 03 | 1095 | +0.0135% |
| 04 | 1095 | +0.1066% |
| 05 | 1095 | +0.0935% |
| 06 | 1095 | -0.0316% |
| 07 | 1095 | +0.0553% |
| 08 | 1095 | -0.0465% |
| 09 | 1095 | -0.0436% |
| 10 | 1095 | +0.0807% |
| 11 | 1095 | +0.0111% |
| 12 | 1095 | -0.0597% |
| 13 | 1095 | -0.0213% |
| 14 | 1095 | -0.0926% |
| 15 | 1095 | -0.0091% |
| 16 | 1095 | -0.0159% |
| 17 | 1095 | +0.0146% |
| 18 | 1095 | +0.0165% |
| 19 | 1095 | +0.0384% |
| 20 | 1095 | +0.0165% |
| 21 | 1095 | +0.0441% |
| 22 | 1095 | +0.0999% |
| 23 | 1095 | -0.0243% |

## 发现门明细

- PASS - 15 bps return > 0
- PASS - 15 bps Sharpe >= 0.40
- PASS - 25 bps/side return > 0
- PASS - at least two positive cold-start years
- FAIL - Sharpe beats buy-and-hold
- PASS - return and Sharpe beat the weekend-only placebo
- FAIL - matched-random one-sided p < 0.10
- PASS - at least fifty held episodes

## Provenance

- Source fingerprint (1h): `b944b1f7186c18cd`
- Aggregated fingerprint (1d): `90ece55e00daf3d7`
- Bars (1d): 1095
- Range: `2021-01-01..2023-12-31`
- Query hard end: `2024-01-01 00:00 UTC` (exclusive)
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed 1d decision, next 1d open fill, ON_ENTRY, long/cash
- Registered attempts (cumulative): 44
