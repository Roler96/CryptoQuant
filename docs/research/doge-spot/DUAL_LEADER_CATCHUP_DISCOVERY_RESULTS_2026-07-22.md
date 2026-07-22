# DOGE 双领导币追赶策略发现结果 (2021-2023)

> 本进程在数据库层硬截止 2024-01-01; 没有读取 2024、2025 或 2026。

## 结论

**DISCOVERY FAIL**

## 冻结主版本

| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| -33.95% | -1.47 | -37.36% | 207 | -0.20% | -36.67% | -40.44% | -46.94% |

## 冷启动自然年

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | -7.40% | -0.72 | -11.19% | 54 |
| 2022 | -26.65% | -3.28 | -26.71% | 72 |
| 2023 | -2.75% | -0.31 | -7.89% | 81 |

## 固定邻域与机制反证

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| q85 | -33.96% | -1.31 | -36.58% | 258 | -0.16% |
| q95 | -9.94% | -0.47 | -16.14% | 118 | -0.08% |
| hold8 | -26.63% | -1.40 | -32.22% | 207 | -0.15% |
| hold18 | -22.60% | -0.73 | -32.67% | 207 | -0.12% |
| leader_only | -18.57% | -0.63 | -24.92% | 255 | -0.08% |
| already_led | +8.09% | 0.37 | -7.23% | 123 | +0.07% |

## 匹配随机入场

- Observed episode return: `-33.95%`
- Random median: `-6.97%`
- Random P5-P95: `-29.72%` .. `+37.34%`
- Raw one-sided p: `0.979302`
- Sidak-adjusted p (5 tradable versions): `1.000000`

## 冻结门明细

- FAIL - 15 bps return > 0
- FAIL - 15 bps Sharpe >= 0.50
- FAIL - MaxDD <= 20%
- PASS - at least 30 closed trades
- FAIL - at least two positive cold-start years
- FAIL - 25 bps/side return > 0
- FAIL - return less best closed trade > 0
- FAIL - episode bootstrap P5 > 0
- FAIL - all four fixed structural neighbors profitable
- FAIL - catch-up beats leader-only on mean episode and Sharpe
- FAIL - catch-up mean episode beats already-led sign placebo
- FAIL - year/holding matched random Sidak-adjusted p <= 0.10

## Provenance

- DOGE fingerprint: `b944b1f7186c18cd`
- BTC fingerprint: `fb5c259990af5f1b`
- ETH fingerprint: `529bbeddd6a0c14f`
- Bars: 26280
- Range: `2021-01-01..2023-12-31`
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed 1h decision, next open fill, 25% spot target
- Protocol: `DUAL_LEADER_CATCHUP_PROTOCOL_2026-07-22.md`

按预注册规则, 本版本在这里永久停止; 不得打开 2024, 也不得从固定邻域挑选替代品。
