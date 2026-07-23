# DOGE 单资产尾部条件反转发现结果 (TCR v1, 2021-2023)

> 数据库层排他硬截止 2024-01-01; 未读取后续年度。单资产, 不用 BTC/ETH。
> 承接方向 C: 只在自身急跌尾部稀疏做多, 试图收割反转毛 edge 的一小片而不被成本吞没。

## 结论

**DISCOVERY FAIL**

## 冻结主版本 (N=6, q=0.05, M=12, 15bps)

| Return | Sharpe | MaxDD | Trades | Mean episode | Less best 1 | 25bps | Bootstrap P5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| +12.94% | 0.42 | -15.82% | 132 | +0.10% | +7.51% | +5.70% | -10.68% |

## 冷启动自然年 (main, 15bps)

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | -8.38% | -0.47 | -15.82% | 30 |
| 2022 | +13.82% | 1.36 | -7.11% | 48 |
| 2023 | +8.30% | 1.77 | -1.92% | 54 |

## 固定邻域与机制消融 (15bps)

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| q025 | +8.80% | 0.35 | -12.15% | 70 | +0.13% |
| q10 | +17.09% | 0.52 | -11.90% | 205 | +0.08% |
| hold6 | -12.04% | -0.62 | -16.54% | 138 | -0.09% |
| hold24 | +8.75% | 0.28 | -18.48% | 120 | +0.08% |
| no_confirm | -5.45% | -0.10 | -19.02% | 181 | -0.03% |
| plain_dip | -27.17% | -0.76 | -39.43% | 387 | -0.08% |

## 匹配随机入场

- Observed episode return: `+12.94%`
- Random median: `-5.80%`
- Random P5-P95: `-23.72%` .. `+25.41%`
- Raw one-sided p: `0.125387`
- Sidak-adjusted p (5 versions): `0.488226`

## 冻结门明细

- PASS — 15 bps return > 0
- FAIL — 15 bps Sharpe >= 0.50
- PASS — MaxDD <= 20%
- PASS — at least 20 closed trades
- PASS — at least two positive cold-start years
- PASS — 25 bps/side return > 0
- PASS — return less best closed trade > 0
- FAIL — episode bootstrap P5 > 0
- FAIL — all four fixed neighbors profitable
- PASS — main beats plain_dip on Sharpe and mean episode
- PASS — main mean episode beats no_confirm ablation
- FAIL — year/holding matched random Sidak-adjusted p <= 0.10

## Provenance

- DOGE fingerprint: `b944b1f7186c18cd`
- Bars: 26280
- Range: `2021-01-01..2023-12-31`
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed 1h decision, next open fill, 25% spot target
- Protocol: `TAIL_REVERSAL_1H_PROTOCOL_2026-07-23.md`

按冻结规则, TCR v1 在 discovery 永久停止; 不读取 2024, 不从邻域替补, 不调参。
