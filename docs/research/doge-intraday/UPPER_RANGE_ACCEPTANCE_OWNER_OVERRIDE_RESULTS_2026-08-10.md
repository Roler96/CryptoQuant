# DOGE 上沿价格接受 (URA v1) 发现结果

- 结论: `OWNER_OVERRIDE_G2_FAIL`
- 协议: `docs/research/doge-intraday/UPPER_RANGE_ACCEPTANCE_PROTOCOL_2026-08-10.md`
- Holdout accessed: `false`
- Owner override: `true`
- Execution gate: `OPEN_BY_OWNER_OVERRIDE`
- 数据: 38,688 根 DOGE-USDT 1h; SHA-256 `11459117bfa9dcd09d942e9f0b4dfaf29c5e8bbb92272147cbbf8ba7bb28427f`

## Gates

| Gate | Result |
|---|---|
| G0_integrity | PASS |
| G1_capacity | FAIL |
| G2_main_economics | FAIL |
| G3_stress_outliers | NOT_RUN |
| G4_calendar | NOT_RUN |
| G5_bootstrap | NOT_RUN |
| G6_neighborhood | NOT_RUN |
| G7_mechanism | NOT_RUN |
| G8_matched_random | NOT_RUN |

## Capacity

- Continuous episodes: 167
- Cold-start segments: `{"2021": 28, "2022": 38, "2023": 43, "2024": 44, "2025-partial": 14}`
- Frozen condition funnel: `{"eligible_decisions": 38639, "positive_known_volume": 38581, "nonconstant_reference_range": 38581, "minimum_upper_share": 2902, "maximum_lower_share": 2567, "current_upper_location": 699, "raw_signals": 535, "accepted_schedule": 167}`

## Main (15 bps/side)

| Return | CAGR | Sharpe | MaxDD | Episodes | Win rate | PF |
|---:|---:|---:|---:|---:|---:|---:|
| -21.64% | -5.37% | -0.5101 | -28.94% | 167 | +44.91% | 0.7159565694739705 |

最长回撤: 35477 小时; 最终未平仓: `false`。

## 裁决

G1/G2 任一失败后, stress、邻域、消融、bootstrap、matched-random 与 holdout 均按冻结协议标记 `NOT_RUN`。

Owner override 仅打开执行边界，没有改变门槛：G1 仍为 `FAIL`。G2 三项全部失败：总收益要求 `>0`，实际 `-21.64%`；Sharpe 要求 `>=0.60`，实际 `-0.5101`；signed MaxDD 要求 `>=-20%`，实际 `-28.94%`。因此 URA v1 不只是样本不足，主经济性也明确失败，后续 G3-G8 继续短路。
