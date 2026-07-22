# DOGE VCSE v2 简化版探索 (2026-07-22)

> `no_clv + no_volume` 由已见的 v1 全历史消融启发; 以下是受污染的 post-hoc exploration, 不是 OOS。

## 结论

**EXPLORATION FAIL**

- PASS - all phases profitable, at least 3/4 Sharpe >= 0.60, all MaxDD <= 50%
- PASS - 25 and 50 bps/side stress returns remain positive
- PASS - block bootstrap P5 is positive at sizes 2, 4 and 8
- PASS - every entry-year jackknife return is positive
- FAIL - matched random-entry family-adjusted p < 0.05
- PASS - every 4h phase has at least 30 closed trades

## v1 与 v2 phase 0 对照

| Version | Return | Sharpe | MaxDD | Trades | Less best 1 |
|---|---:|---:|---:|---:|---:|
| v1 | +383.81% | 0.95 | -38.00% | 46 | +264.00% |
| v2 | +1616.60% | 1.23 | -38.65% | 57 | +1148.45% |

## v2 4h 聚合相位

| Phase | Return | Sharpe | MaxDD | Trades | Less best 1 |
|---:|---:|---:|---:|---:|---:|
| 0h | +1616.60% | 1.23 | -38.65% | 57 | +1148.45% |
| 1h | +2086.36% | 1.32 | -39.42% | 50 | +1561.69% |
| 2h | +2185.85% | 1.29 | -43.05% | 56 | +1666.86% |
| 3h | +1589.43% | 1.19 | -35.77% | 57 | +1043.54% |

## phase 0 成本压力

| Cost/side | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 15 bps | +1616.60% | 1.23 | -38.65% | 57 |
| 25 bps | +1431.65% | 1.19 | -39.02% | 57 |
| 50 bps | +1051.82% | 1.09 | -39.92% | 57 |

## phase 0 circular block bootstrap

| Block trades | P(loss) | P5 | Median | P95 |
|---:|---:|---:|---:|---:|
| 2 | +2.01% | +56.90% | +1382.69% | +29097.80% |
| 4 | +0.87% | +96.93% | +1387.18% | +24225.87% |
| 8 | +0.35% | +143.01% | +1441.18% | +19061.05% |

## phase 0 自然年 jackknife

| Removed entry year | Removed trades | Remaining return |
|---:|---:|---:|
| 2021 | 8 | +207.28% |
| 2022 | 8 | +918.13% |
| 2023 | 10 | +1626.06% |
| 2024 | 10 | +904.95% |
| 2025 | 16 | +1473.37% |
| 2026 | 5 | +1645.70% |

## phase 0 匹配随机入场零假设

- Observed episode return: `+1616.60%`
- Random median: `+4.57%`
- Random P5-P95: `-77.21%` .. `+822.32%`
- Raw one-sided p: `0.022298`
- Sidak-adjusted p (18 trials): `0.333625`

## 解释与边界

- v2删除了两个确认项, 但压缩、突破、区间扩张和全部退出规则保持不变。
- 若通过, 它也只能与v1并行从零收集forward样本; 历史优势不能用于真实资金。
- v2是由全历史消融启发的第18次研究尝试, 不得把结果称为独立发现。
- 本轮之后不再在同一历史上继续删除过滤项或修改退出。

## Provenance

- 1h data fingerprint: `a03a0968f222a477`
- 1h bars: 48631
- Range: 2021-01-01 00:00:00+00:00..2026-07-20 06:00:00+00:00
- Input: DOGE-USDT spot OHLCV only
- Protocol: `VCSE_V2_EXPLORATION_PROTOCOL_2026-07-22.md`
