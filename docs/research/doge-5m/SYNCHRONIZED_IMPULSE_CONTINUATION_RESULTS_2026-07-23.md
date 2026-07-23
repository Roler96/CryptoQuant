# DOGE 5m 现货确认的永续冲击延续结果 (SIC v1)

**DISCOVERY FAIL。**

SIC 在极端 15m 永续价格/量能冲击且现货同向确认后,
于下一根 5m open 顺势持有 0.5x 永续 30 分钟。

## 发现窗口 (2021-2023)

| Metric | 主成本 15bps/边 | 压力 25bps/边 |
|---|---:|---:|
| Return | -90.70% | -96.53% |
| Sharpe | -2.22 | -3.20 |
| MaxDD | -91.56% | -96.76% |
| Episodes | 981 | 981 |
| Long / Short | 502 / 479 | 502 / 479 |
| Win rate | +31.29% | +26.91% |
| Mean episode | -0.23% | -0.33% |
| Return less best PnL | -106.71% | -112.08% |
| Bootstrap P5 | -95.77% | -98.42% |

### 年度

| Year | Return | Sharpe | MaxDD | Episodes | Long/Short |
|---:|---:|---:|---:|---:|---:|
| 2021 | -61.64% | -1.62 | -69.47% | 319 | 183/136 |
| 2022 | -52.17% | -3.47 | -53.81% | 357 | 168/189 |
| 2023 | -49.32% | -4.06 | -49.62% | 305 | 151/154 |

### 冻结邻域

| Version | Return | Sharpe | MaxDD | Episodes |
|---|---:|---:|---:|---:|
| main | -90.70% | -2.22 | -91.56% | 981 |
| score3 | -97.86% | -3.35 | -98.34% | 1806 |
| score5 | -85.34% | -2.01 | -87.33% | 579 |
| volume2 | -91.00% | -2.26 | -91.83% | 993 |
| volume5 | -88.04% | -2.02 | -89.66% | 918 |
| hold3 | -88.07% | -2.66 | -90.09% | 1063 |
| hold12 | -91.80% | -1.98 | -92.79% | 856 |

### 随机入场与发现门

- Observed compound: `-90.70%`
- Matched-random median: `-77.28%`
- raw p: `1.0000`; Sidak p (7): `1.0000`

- FAIL: 15bps/side return > 0
- FAIL: annualized Sharpe >= 0.75
- FAIL: MaxDD <= 20%
- PASS: at least 100 episodes
- FAIL: at least two positive discovery years
- FAIL: 25bps/side stress return > 0
- FAIL: return less best episode PnL > 0
- FAIL: episode bootstrap P5 > 0
- FAIL: at least five of seven frozen versions positive
- FAIL: matched-random Sidak p <= 0.10
- PASS: no unmodelled funding crossings

### 事后符号诊断 (非候选)

- 原方向零成本复合收益: `-59.33%`; 平均每笔 `-0.08%`
- 相同入场/持仓机械反向、计主成本: `-55.91%`; 平均每笔 `-0.07%`
- 该诊断在看到 continuation 失败后才计算, 不得作为新候选或用来打开后续年份。

## 顺序验证

发现门未通过, 最终 runner 没有查询或计算 2024+ 的 SIC 收益。

## 数据与限制

- Paired bars: `315360`; range `2021-01-01 00:00:00+00:00..2023-12-31 23:55:00+00:00`
- Raw confirmed bars: `2514` (positive `1326`, negative `1188`)
- Spot fingerprint: `5b22421e745b4839`
- Swap fingerprint: `1301a638ac69d89f`
- K 线 volume 不区分主动方向或强平, 且没有历史盘口和实际动态 funding schedule。
