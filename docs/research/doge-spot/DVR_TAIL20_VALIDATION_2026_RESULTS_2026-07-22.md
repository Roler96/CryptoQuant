# DOGE DVR-T20 2026 冻结验证

> 策略已在2025 pre-freeze审计失败; 2026只作用户要求的冻结参数诊断, 不能挽救或晋级策略。

**INCONCLUSIVE - 2026 INCOMPLETE**

数据覆盖: `2026-01-01..2026-07-22T00:00:00+00:00`

| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return |
|---:|---:|---:|---:|---:|---:|
| -4.56% | -1.21 | -6.89% | 9 | -4.99% | -4.98% |

## 完整年度冻结门 (当前只显示进度, 不裁决)

- FAIL - 15 bps return > 0
- FAIL - 25 bps/side return > 0
- PASS - MaxDD <= 20%
- PASS - at least four closed trades
- FAIL - return less best closed trade > 0
- FAIL - episode bootstrap P5 > 0
- FAIL - matched-random one-sided p < 0.10

## 匹配随机入场

- Observed: `-4.56%`
- Null median: `-5.05%`
- Null P5-P95: `-13.14%` .. `+4.75%`
- One-sided p: `0.466553`

## Provenance

- Data fingerprint: `20b0b525bcec2647`
- Strategy source SHA256: `3d0843ebe4df1d217fb24f90b2b03e3faa636474decb586a55ba16127db8adba`
- Holdout access count: 1
- Split fingerprint: `46405e6c105c2764`
- Bars loaded: 2028
- Range loaded: `2021-01-01T00:00:00+00:00..2026-07-21T00:00:00+00:00`
- Query end fixed at `2027-01-01 00:00 UTC` (exclusive), not latest
- Candidate-level decision remains REJECTED regardless of 2026
