# DOGE 特异性卖压反转发现结果 (ISR v1, 2021-2023)

> 本进程在数据库查询层排他硬截止 2024-01-01; 未读取后续年度。

## 结论

**DISCOVERY FAIL**

## 冻结主版本

| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| -12.36% | -0.58 | -14.93% | 64 | -0.20% | -15.25% | -15.12% | -25.86% |

## 冷启动自然年

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | -10.93% | -1.14 | -13.73% | 20 |
| 2022 | -0.66% | -0.06 | -8.80% | 24 |
| 2023 | -0.96% | -0.31 | -3.58% | 20 |

## 固定邻域与机制消融

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| q025 | -11.85% | -0.59 | -18.46% | 33 | -0.37% |
| q10 | -5.89% | -0.19 | -14.25% | 110 | -0.05% |
| hold6 | -10.21% | -0.76 | -11.95% | 66 | -0.16% |
| hold24 | -27.13% | -1.06 | -28.62% | 59 | -0.52% |
| no_market_filter | +8.18% | 0.33 | -11.84% | 105 | +0.08% |
| plain_reversal | -14.79% | -0.37 | -34.94% | 371 | -0.04% |

## 匹配随机入场

- Observed episode return: `-12.36%`
- Random median: `-2.52%`
- Random P5-P95: `-16.52%` .. `+23.38%`
- Raw one-sided p: `0.870313`
- Sidak-adjusted p (5 tradable versions): `0.999963`

## 冻结门明细

- FAIL — 15 bps return > 0
- FAIL — 15 bps Sharpe >= 0.50
- PASS — MaxDD <= 20%
- PASS — at least 20 closed trades
- FAIL — at least two positive cold-start years
- FAIL — 25 bps/side return > 0
- FAIL — return less best closed trade > 0
- FAIL — episode bootstrap P5 > 0
- FAIL — all four fixed structural neighbors profitable
- FAIL — main beats plain reversal on Sharpe and mean episode
- FAIL — main mean episode beats no-market-filter ablation
- FAIL — year/holding matched random Sidak-adjusted p <= 0.10

## Provenance

- DOGE fingerprint: `b944b1f7186c18cd`
- BTC fingerprint: `fb5c259990af5f1b`
- ETH fingerprint: `529bbeddd6a0c14f`
- Bars: 26280
- Range: `1609459200000 .. 1704063600000`
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed 1h decision, next open fill, 25% spot target
- Protocol: `IDIOSYNCRATIC_SELLOFF_REVERSAL_PROTOCOL_2026-07-22.md`

按冻结规则, ISR v1 在 discovery 永久停止; 不读取2024, 也不从邻域替补。
