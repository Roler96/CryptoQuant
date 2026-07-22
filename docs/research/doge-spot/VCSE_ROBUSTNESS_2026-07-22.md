# DOGE VCSE v1 稳健性审计 (2026-07-22)

> 本报告执行预先冻结的稳健性协议; 历史已被访问, 不是 OOS。

## 结论

**ROBUSTNESS FAIL**

- PASS - all four 4h phases are profitable and at least 3/4 Sharpe >= 0.60
- PASS - all four 4h phases have MaxDD <= 50%
- PASS - block bootstrap P5 is positive at sizes 2, 4 and 8
- PASS - every entry-year jackknife return is positive
- FAIL - matched random-entry family-adjusted p < 0.05

## 4h 聚合相位

| Phase | Return | Sharpe | MaxDD | Trades | Less best 1 |
|---:|---:|---:|---:|---:|---:|
| 0h | +383.81% | 0.95 | -38.00% | 46 | +264.00% |
| 1h | +146.44% | 0.63 | -39.78% | 37 | +58.65% |
| 2h | +1766.94% | 1.25 | -40.43% | 42 | +1200.71% |
| 3h | +1936.18% | 1.28 | -33.68% | 45 | +1087.12% |

## Circular block bootstrap (phase 0)

| Block trades | P(loss) | P5 | Median | P95 |
|---:|---:|---:|---:|---:|
| 2 | +4.85% | +1.22% | +369.07% | +2651.77% |
| 4 | +2.60% | +21.27% | +367.65% | +1975.01% |
| 8 | +0.52% | +73.26% | +388.85% | +1151.72% |

## 自然年 jackknife (phase 0)

| Removed entry year | Removed trades | Remaining return |
|---:|---:|---:|
| 2021 | 5 | +244.67% |
| 2022 | 8 | +213.86% |
| 2023 | 8 | +381.61% |
| 2024 | 8 | +146.39% |
| 2025 | 13 | +334.05% |
| 2026 | 4 | +375.76% |

## 匹配随机入场零假设 (phase 0)

- VCSE observed episode return: `+383.81%`
- Random median: `-3.73%`
- Random P5-P95: `-74.27%` .. `+482.17%`
- Raw one-sided p: `0.067793`
- Sidak-adjusted p (17 trials): `0.696815`

## 证据边界

- 所有数字仍来自已被研究过的同一段历史, 只能削弱或保留假设, 不能创造 OOS 证据。
- 相位审计改变信号观察窗口, 也会改变具体交易; 它检验的是时间锚定敏感性。
- block bootstrap只保留交易序列的局部聚集, 不能模拟价格制度永久改变。
- 随机零假设控制入场年份和持仓时长, 但未控制月度市场状态。
- v1规则保持冻结; 任何简化版必须作为新的、受污染的探索假设单独登记。

## Provenance

- 1h data fingerprint: `a03a0968f222a477`
- 1h bars: 48631
- Range: 2021-01-01 00:00:00+00:00..2026-07-20 06:00:00+00:00
- Input: DOGE-USDT spot OHLCV only
- Protocol: `VCSE_ROBUSTNESS_PROTOCOL_2026-07-22.md`
