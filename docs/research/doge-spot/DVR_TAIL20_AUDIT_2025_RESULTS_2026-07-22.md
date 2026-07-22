# DOGE DVR-T20 2025 Pre-freeze 审计结果

> 策略参数与通过2024验证的版本完全相同; 本报告是第一次打开2025。

**PRE-FREEZE FAIL**

| Return | Sharpe | MaxDD | Trades | Less best 1 | 25bps return |
|---:|---:|---:|---:|---:|---:|
| -8.51% | -0.63 | -13.27% | 5 | -10.24% | -8.74% |

## 审计门

- FAIL - 2025 15 bps return > 0
- FAIL - 2025 Sharpe >= 0.20
- PASS - 2025 MaxDD <= 20%
- FAIL - 2025 25 bps/side return > 0
- FAIL - 2025 return less best closed trade > 0
- PASS - 2025 at least four closed trades
- FAIL - pooled circular block-bootstrap P5 > 0 at sizes 2 and 4
- PASS - every pooled entry-year jackknife return > 0
- FAIL - 2025 matched-random one-sided p < 0.10

## Pooled 2021-2025 block bootstrap

| Block episodes | P5 | Median | P95 | P(loss) |
|---:|---:|---:|---:|---:|
| 2 | -10.58% | +160.93% | +995.15% | +7.54% |
| 4 | -5.68% | +168.29% | +899.17% | +6.26% |

## 2025 匹配随机入场

- Observed: `-8.51%`
- Null median: `-5.23%`
- Null P5-P95: `-17.76%` .. `+13.19%`
- One-sided p: `0.641336`

## Provenance

- Data fingerprint: `46a956166b981e2d`
- Strategy source SHA256: `3d0843ebe4df1d217fb24f90b2b03e3faa636474decb586a55ba16127db8adba`
- Bars loaded: 1826
- Range loaded: `2021-01-01..2025-12-31`
- Query hard end: `2026-01-01 00:00 UTC` (exclusive)
- 2025 evaluation is cold-start; pooled robustness is explicitly in-sample
