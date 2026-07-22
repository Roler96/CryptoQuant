# DOGE DVR 尾部风险版本发现结果 (2021-2023)

> 查询在数据库层硬截止于 2024-01-01; 后续年度未读取。

## 主版本

| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps | Gate |
|---:|---:|---:|---:|---:|---:|---|
| +80.62% | 0.67 | -25.86% | 21 | -5.47% | +78.65% | FAIL |

## 冷启动自然年

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | +74.87% | 1.15 | -19.01% | 8 |
| 2022 | +0.82% | 0.14 | -20.73% | 8 |
| 2023 | +2.45% | 0.27 | -9.78% | 5 |

## 风险邻域与反证

| Version | Return | Sharpe | MaxDD | Trades | Less best 1 |
|---|---:|---:|---:|---:|---:|
| trail20 | +85.82% | 0.72 | -19.71% | 21 | +8.04% |
| trail25 | +80.62% | 0.67 | -25.86% | 21 | -5.47% |
| trail30 | +64.29% | 0.59 | -30.30% | 21 | -5.70% |
| no_trail | +107.05% | 0.70 | -47.02% | 21 | +7.50% |

## 发现门明细

- PASS - 15 bps return > 0
- PASS - 15 bps Sharpe >= 0.60
- PASS - MaxDD <= 30%
- PASS - at least two positive cold-start years
- PASS - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- PASS - at least six closed trades
- PASS - 20% and 30% fixed trail neighbors profitable
- PASS - trail strictly lowers MaxDD versus no-trail and remains profitable

## Provenance

- Data fingerprint: `90ece55e00daf3d7`
- Bars: 1095
- Range: `2021-01-01..2023-12-31`
- Query hard end: `2024-01-01 00:00 UTC` (exclusive)
- Registered family attempts including prior work: 39
- Execution: closed 1d decision, next 1d open fill, ON_ENTRY
