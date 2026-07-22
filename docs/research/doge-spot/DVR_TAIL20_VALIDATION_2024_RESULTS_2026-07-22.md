# DOGE DVR-T20 2024 顺序验证结果

> DVR-T20 从2021-2023 discovery事后晋级; 本报告是第一次打开2024。

**VALIDATION PASS**

| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return |
|---:|---:|---:|---:|---:|---:|
| +65.76% | 1.93 | -18.40% | 11 | +4.78% | +64.81% |

## 冻结门

- PASS - 15 bps return > 0
- PASS - 15 bps Sharpe >= 0.40
- PASS - MaxDD <= 25%
- PASS - 25 bps/side return > 0
- PASS - return less best closed trade > 0
- PASS - at least four closed trades

## 其他统计

- Win rate: `+18.18%`
- Profit factor: `7.69`
- Bootstrap P5: `-10.77%`
- Bootstrap P(loss): `+12.42%`
- Open position at year end: `False`

## Provenance

- Data fingerprint: `1958b213fa08e3c9`
- Strategy source SHA256: `3d0843ebe4df1d217fb24f90b2b03e3faa636474decb586a55ba16127db8adba`
- Bars loaded: 1461
- Range loaded: `2021-01-01..2024-12-31`
- Query hard end: `2025-01-01 00:00 UTC` (exclusive)
- Evaluation: cold-start `2024-01-01 .. 2025-01-01`
- Execution: closed 1d decision, next 1d open fill, ON_ENTRY
