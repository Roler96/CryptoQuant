# DOGE 方向性状态策略发现结果 (2021-2023)

> 本进程只查询 2024-01-01 以前的数据; 2024、2025、2026 未读取。

## 主候选

| Candidate | Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| dvr28 | +420.09% | 0.98 | -69.49% | 21 | -20.35% | +398.20% | FAIL |
| mpe_main | -65.38% | -0.27 | -75.92% | 128 | -71.85% | -68.30% | FAIL |
| deb_main | +125.73% | 0.72 | -83.36% | 10 | -246.91% | +121.04% | FAIL |

## 冷启动自然年

| Candidate | 2021 | 2022 | 2023 |
|---|---:|---:|---:|
| dvr28 | +416.06% | -3.65% | +4.60% |
| mpe_main | -61.36% | -11.64% | +1.32% |
| deb_main | +322.01% | -32.15% | -21.17% |

## 固定结构邻域

| Candidate | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| dvr21 | +336.93% | 0.93 | -74.86% | 30 |
| dvr42 | +89.64% | 0.66 | -86.72% | 16 |
| mpe_fast | +171.78% | 0.75 | -81.98% | 138 |
| mpe_slow | -34.62% | -0.07 | -66.87% | 86 |
| deb_fast | +621.62% | 1.06 | -66.78% | 12 |
| deb_slow | +216.56% | 0.80 | -74.57% | 6 |

## 发现门明细

### dvr28

- PASS - 15 bps return > 0
- PASS - 15 bps Sharpe >= 0.40
- FAIL - MaxDD <= 55%
- PASS - at least two positive cold-start years
- PASS - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- PASS - at least six closed trades
- PASS - both fixed structural neighbors profitable

### mpe_main

- FAIL - 15 bps return > 0
- FAIL - 15 bps Sharpe >= 0.40
- FAIL - MaxDD <= 55%
- FAIL - at least two positive cold-start years
- FAIL - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- PASS - at least six closed trades
- FAIL - both fixed structural neighbors profitable

### deb_main

- PASS - 15 bps return > 0
- PASS - 15 bps Sharpe >= 0.40
- FAIL - MaxDD <= 55%
- FAIL - at least two positive cold-start years
- PASS - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- PASS - at least six closed trades
- PASS - both fixed structural neighbors profitable

## Provenance

- Source fingerprint: `b944b1f7186c18cd`
- Aggregated fingerprint: `90ece55e00daf3d7`
- Bars: 1095
- Range: `2021-01-01..2023-12-31`
- Query hard end: `2024-01-01 00:00 UTC` (exclusive)
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed daily bar decision, next daily open fill, ON_ENTRY
- Registered attempts: 9
