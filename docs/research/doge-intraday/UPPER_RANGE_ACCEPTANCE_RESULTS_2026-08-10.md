# DOGE 上沿价格接受 (URA v1) 发现结果

- 结论: `DISCOVERY_FAIL`
- 协议: `docs/research/doge-intraday/UPPER_RANGE_ACCEPTANCE_PROTOCOL_2026-08-10.md`
- Holdout accessed: `false`
- 数据: 38,688 根 DOGE-USDT 1h; SHA-256 `11459117bfa9dcd09d942e9f0b4dfaf29c5e8bbb92272147cbbf8ba7bb28427f`

## Gates

| Gate | Result |
|---|---|
| G0_integrity | PASS |
| G1_capacity | FAIL |
| G2_main_economics | NOT_RUN |
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

## 裁决

G1/G2 任一失败后, stress、邻域、消融、bootstrap、matched-random 与 holdout 均按冻结协议标记 `NOT_RUN`。

Mode-B 独立审计：`VALID`。详见 `UPPER_RANGE_ACCEPTANCE_MODE_B_AUDIT_2026-08-10.md`。
