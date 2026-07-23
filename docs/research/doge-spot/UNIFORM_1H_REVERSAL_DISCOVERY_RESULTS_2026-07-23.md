# DOGE 均匀 1h 反转发现结果 (U1R v1, 2021-2023)

> 本进程在数据库层排他硬截止 2024-01-01; 未读取后续年度。单资产, 不用 BTC/ETH。
> **预先声明本版本预期 FAIL**: 价值是负面基线与成本分解, 不是 edge。

## 结论

**DISCOVERY FAIL**

## 冻结主版本 (k=1, deadband=0, 15bps)

| Return | Sharpe | MaxDD | Trades | Mean hold h | Less best 1 | 25bps | Bootstrap P5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| -100.00% | -5.06 | -100.00% | 7027 | 1.9 | -132.40% | -100.00% | -100.00% |

## 成本阶梯 (main, 每边 bps)

| Cost | Return | Sharpe | Trades |
|---|---:|---:|---:|
| 0bps | +4116.07% | 1.72 | 7027 |
| 15bps | -100.00% | -5.06 | 7027 |
| 25bps | -100.00% | -9.54 | 7027 |

Buy&Hold 参照 (15bps): Return +1804.49%, Sharpe 1.38, MaxDD -93.18%, Trades 0

## 冷启动自然年 (main, 15bps)

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | -99.55% | -2.84 | -99.71% | 2345 |
| 2022 | -99.71% | -6.83 | -99.71% | 2357 |
| 2023 | -99.78% | -10.77 | -99.78% | 2324 |

## 冻结家族 (15bps)

| Version | Return | Sharpe | MaxDD | Trades | Mean episode |
|---|---:|---:|---:|---:|---:|
| k2 | -100.00% | -3.07 | -100.00% | 4755 | -0.21% |
| k3 | -99.97% | -2.15 | -99.98% | 3814 | -0.18% |
| k6 | -99.62% | -1.34 | -99.91% | 2756 | -0.16% |
| db0.5 | -99.90% | -1.74 | -99.94% | 3128 | -0.19% |
| db1.0 | -98.43% | -0.81 | -98.76% | 1458 | -0.20% |

## 冻结门明细

- FAIL — 15 bps return > 0
- FAIL — 15 bps Sharpe >= 0.50
- FAIL — MaxDD <= 35%
- PASS — at least 20 closed trades
- FAIL — at least two positive cold-start years
- FAIL — 25 bps/side return > 0
- FAIL — return less best closed trade > 0
- FAIL — episode bootstrap P5 > 0
- FAIL — main 15bps return > buy&hold net return
- FAIL — at least four of six versions positive at 15bps

## Provenance

- DOGE fingerprint: `b944b1f7186c18cd`
- Bars: 26280
- Range: `2021-01-01..2023-12-31`
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Execution: closed 1h decision, next open fill, long/cash spot
- Protocol: `UNIFORM_1H_REVERSAL_PROTOCOL_2026-07-23.md`

按冻结规则, U1R v1 在 discovery 永久停止; 不读取 2024, 也不从邻域替补, 不调参。

**关键读法**: 0bps 毛收益 +4116% / Sharpe 1.72 说明反转信号的毛 edge 巨大且真实, 但需要 7027 笔交易 (日均 6.5 笔, 平均持有 1.9h); 15bps/边下换手成本把一切吞没到 -100%。**约束是换手频率, 不是信号有无。** deadband 邻域 (db1.0: 1458 笔仍 -98.4%) 证实少交易有用但远不够。这为方向 A (尾部条件反转, 靠稀疏交易过成本墙) 指明命题: 能否只收割这块毛 edge 的一小片、同时把交易压到能存活的频率。
