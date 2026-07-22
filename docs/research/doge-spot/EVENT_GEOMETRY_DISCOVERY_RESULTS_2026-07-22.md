# DOGE 小时事件几何发现结果 (2021-2023)

> 查询在数据库层硬截止于 2024-01-01; 后续年度未读取。

## 主候选

| Candidate | Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| dac4 | -71.28% | -0.43 | -86.84% | 217 | -116.44% | -81.39% | FAIL |
| pjs24 | +6.56% | 0.28 | -57.42% | 73 | -46.26% | -7.92% | FAIL |

## 冷启动自然年

| Candidate | 2021 | 2022 | 2023 |
|---|---:|---:|---:|
| dac4 | -4.27% | -59.56% | -24.88% |
| pjs24 | +65.05% | -18.27% | -21.01% |

## 全部固定候选与反证

| Name | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| dac3 | -66.97% | -0.34 | -85.50% | 220 |
| dac4 | -71.28% | -0.43 | -86.84% | 217 |
| dac5 | -81.39% | -0.70 | -89.43% | 212 |
| momentum_only | -61.36% | -0.25 | -84.04% | 221 |
| concentrated | +16.56% | 0.44 | -15.15% | 5 |
| pjs12 | -18.15% | 0.05 | -50.45% | 63 |
| pjs24 | +6.56% | 0.28 | -57.42% | 73 |
| pjs36 | -27.24% | 0.04 | -70.73% | 90 |
| first_jump | -16.20% | 0.20 | -72.19% | 163 |

## 发现门明细

### dac4

- FAIL - 15 bps return > 0
- FAIL - 15 bps Sharpe >= 0.60
- FAIL - MaxDD <= 40%
- FAIL - at least two positive cold-start years
- FAIL - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- PASS - at least twenty closed trades
- FAIL - both fixed structural neighbors profitable
- FAIL - mechanism ablation passed

### pjs24

- PASS - 15 bps return > 0
- FAIL - 15 bps Sharpe >= 0.60
- FAIL - MaxDD <= 40%
- FAIL - at least two positive cold-start years
- FAIL - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- PASS - at least twenty closed trades
- FAIL - both fixed structural neighbors profitable
- PASS - mechanism ablation passed

## Provenance

- Data fingerprint: `b944b1f7186c18cd`
- Bars: 26280
- Range: `2021-01-01..2023-12-31`
- Query hard end: `2024-01-01 00:00 UTC` (exclusive)
- Registered family attempts including prior work: 35
- Execution: closed 1h decision, next 1h open fill, ON_ENTRY
