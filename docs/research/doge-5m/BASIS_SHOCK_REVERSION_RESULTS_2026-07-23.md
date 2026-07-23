# DOGE 5m 现货-永续基差冲击回归结果 (BSR v1)

**DISCOVERY FAIL。**

这是 5 分钟级双腿日内策略研究, 不是撮合级 HFT。信号在闭合 bar 后产生,
两腿都在下一根 open 以 taker 成本成交; 没有历史盘口或挂单成交假设。

## 发现窗口 (2021-2023)

| Metric | 主成本 15bps/腿/边 | 压力 25bps/腿/边 |
|---|---:|---:|
| Return | +8.07% | +3.80% |
| Sharpe | 1.20 | 0.59 |
| MaxDD | -1.20% | -1.48% |
| Episodes | 20 | 20 |
| Win rate | +75.00% | +35.00% |
| Mean episode | +0.39% | +0.19% |
| Return less best PnL | +6.12% | +2.12% |
| Bootstrap P5 | +3.86% | -0.24% |

### 年度

| Year | Return | Sharpe | MaxDD | Episodes |
|---:|---:|---:|---:|---:|
| 2021 | +8.07% | 2.08 | -1.20% | 20 |
| 2022 | +0.00% | 0.00 | -0.00% | 0 |
| 2023 | +0.00% | 0.00 | -0.00% | 0 |

### 冻结邻域

| Version | Return | Sharpe | MaxDD | Episodes |
|---|---:|---:|---:|---:|
| main | +8.07% | 1.20 | -1.20% | 20 |
| z3 | +14.79% | 1.56 | -1.20% | 26 |
| z5 | +5.64% | 0.99 | -1.20% | 16 |
| floor40 | +7.29% | 1.06 | -1.20% | 29 |
| floor80 | +8.03% | 1.25 | -1.20% | 14 |
| hold6 | +7.85% | 1.01 | -1.74% | 21 |
| hold24 | +8.73% | 1.31 | -1.20% | 16 |

### 随机入场与发现门

- Observed episode compound: `+8.07%`
- Matched-random median: `-5.83%`
- raw p: `0.0001`; Sidak p (7): `0.0007`

- PASS: 15bps/leg/side return > 0
- PASS: annualized Sharpe >= 1.0
- PASS: MaxDD <= 10%
- FAIL: at least 50 closed episodes
- FAIL: at least two positive discovery years
- PASS: 25bps/leg/side stress return > 0
- PASS: return less best episode PnL > 0
- PASS: episode bootstrap P5 > 0
- PASS: at least five of seven frozen versions positive
- PASS: matched-random Sidak p <= 0.10
- PASS: no unmodelled funding crossings

## 顺序验证

发现门未通过, 按预注册规则没有读取 2024/2025/2026 的 BSR 收益;
不能从后续年份寻找救援参数。

## 数据与限制

- Paired bars: `315360`; range `2021-01-01 00:00:00+00:00..2023-12-31 23:55:00+00:00`
- Spot/swap zero-volume bars: `281` / `312`
- Discovery bars with z>=4: `248`; excess basis >=60bps: `413`
- Spot fingerprint: `5b22421e745b4839`
- Swap fingerprint: `1301a638ac69d89f`
- 缺少历史 bid/ask、盘口深度、两腿原子成交、逐笔数据和实际历史 funding schedule;
  即使过门也只能进入实时盘口 shadow, 不批准真实资金。
