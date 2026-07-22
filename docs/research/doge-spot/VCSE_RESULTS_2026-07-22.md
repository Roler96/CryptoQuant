# DOGE VCSE 历史探索结果 (2026-07-22)

> 规则在结果未知时预注册。全部数据早于/等于 forward freeze, 以下不是 OOS。

## 主策略

| Return | CAGR | Sharpe | MaxDD | Trades | PF | Less best 1 |
|---:|---:|---:|---:|---:|---:|---:|
| +383.81% | +32.87% | 0.95 | -38.00% | 46 | 2.12 | +264.00% |

## 自然年

| Year | Return | Sharpe | MaxDD | Closed trades |
|---:|---:|---:|---:|---:|
| 2021 | +40.37% | 1.22 | -16.52% | 5 |
| 2022 | +54.15% | 1.08 | -33.42% | 8 |
| 2023 | +0.46% | 0.13 | -29.36% | 8 |
| 2024 | +96.36% | 1.73 | -38.00% | 8 |
| 2025 | +11.47% | 0.49 | -27.55% | 13 |
| 2026 | +1.69% | 0.25 | -14.31% | 4 |

## 成本压力

| Cost/side | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 15 bps | +383.81% | 0.95 | -38.00% | 46 |
| 25 bps | +341.29% | 0.91 | -38.62% | 46 |
| 50 bps | +250.62% | 0.79 | -40.13% | 46 |

## 单因素邻域

| Variant | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| q15 | +421.74% | 0.99 | -36.18% | 44 |
| q25 | +212.29% | 0.72 | -41.07% | 53 |
| breakout24 | +329.22% | 0.88 | -36.40% | 52 |
| breakout36 | +472.74% | 1.04 | -38.00% | 42 |
| expansion100 | +375.20% | 0.94 | -39.80% | 47 |
| expansion150 | +346.57% | 0.91 | -38.00% | 45 |
| volume125 | +367.33% | 0.93 | -38.00% | 47 |
| volume175 | +419.74% | 0.99 | -38.00% | 43 |
| trail25 | +274.75% | 0.84 | -37.24% | 47 |
| trail35 | +483.93% | 1.01 | -38.00% | 45 |
| hold42 | +582.47% | 1.19 | -32.75% | 46 |
| hold78 | +281.44% | 0.83 | -38.00% | 46 |

## 机制消融

| Variant | Return | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| no_compression | +509.76% | 0.82 | -63.37% | 90 |
| no_volume | +390.71% | 0.96 | -38.00% | 47 |
| no_clv | +1650.28% | 1.23 | -38.65% | 55 |
| breakout_only | +1206.76% | 1.03 | -60.82% | 117 |
| buy_and_hold | +1393.65% | 0.97 | -92.94% | 0 |

## 预注册门槛

**PASS**

- PASS - 15 bps Sharpe >= 0.60
- PASS - MaxDD <= 50%
- PASS - at least 40 closed trades
- PASS - at least 4 positive calendar years
- PASS - 25 bps return remains positive
- PASS - return less best trade remains positive
- PASS - at least 8/12 neighbors profitable
- PASS - at least 6/12 neighbors Sharpe > 0.30
- PASS - breakout-only does not clearly dominate full mechanism

## Provenance

- Data fingerprint: `45de24002c44b5e9`
- Bars: 12157
- Range: 2021-01-01..2026-07-20
- Input: DOGE-USDT spot OHLCV only
- Engine: unified causal loop, next-bar open execution, ON_ENTRY sizing
