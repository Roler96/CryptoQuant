# DOGE DVR 1h 精化发现结果 (DVR-1H v1, 2021-2023)

> 数据库层硬截止 2024-01-01; 单资产。零新调参: 经济参数全部冻结为日线 DVR 现值,
> 唯一变量是执行分辨率。1h 变体须证明分辨率带来净改善才晋级。

## 结论

**DISCOVERY FAIL**

## 三版本对比 (15bps)

| Version | Return | Sharpe | MaxDD | UW d | Trades | Hold h | 25bps | LessBest |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_daily | +85.82% | 0.72 | -19.71% | 563 | 21 | 313.1 | +83.79% | +8.04% |
| full_1h | +31.64% | 0.58 | -21.47% | 563 | 28 | 103.0 | +29.79% | +2.85% |
| hybrid | +46.14% | 0.81 | -20.18% | 563 | 21 | 261.2 | +44.55% | +17.48% |

## 冷启动自然年 (15bps)

### baseline_daily

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | +68.80% | 1.14 | -16.72% | 8 |
| 2022 | +7.45% | 0.46 | -14.16% | 8 |
| 2023 | +2.45% | 0.27 | -9.78% | 5 |

### full_1h

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | +28.73% | 1.08 | -12.94% | 14 |
| 2022 | +9.62% | 0.63 | -12.36% | 10 |
| 2023 | -6.71% | -0.95 | -10.39% | 4 |

### hybrid

| Year | Return | Sharpe | MaxDD | Trades |
|---:|---:|---:|---:|---:|
| 2021 | +26.28% | 1.22 | -11.70% | 8 |
| 2022 | +13.08% | 0.78 | -14.15% | 8 |
| 2023 | +2.34% | 0.24 | -11.03% | 5 |

## 晋级门明细

### full_1h vs baseline_daily (not promoted)
- FAIL — 15bps return > baseline
- FAIL — 15bps Sharpe > baseline
- FAIL — MaxDD <= baseline
- FAIL — 25bps return > 0 and > baseline 25bps
- PASS — at least two positive cold-start years
- PASS — 15bps return > 0 and less-best > 0

### hybrid vs baseline_daily (not promoted)
- FAIL — 15bps return > baseline
- PASS — 15bps Sharpe > baseline
- FAIL — MaxDD <= baseline
- FAIL — 25bps return > 0 and > baseline 25bps
- PASS — at least two positive cold-start years
- PASS — 15bps return > 0 and less-best > 0

## Provenance

- DOGE fingerprint (1h): `b944b1f7186c18cd`
- DOGE fingerprint (1d): `90ece55e00daf3d7`
- 1h bars: 26280, 1d bars: 1095
- Range: `2021-01-01..2023-12-31`
- Costs: 10 bps fee + 5 bps slippage per side; 25 bps stress
- Frozen economics: horizon 28d, entry 0.60, exit 0.45, trail 0.20, size 0.25
- Protocol: `DVR_1H_REFINEMENT_PROTOCOL_2026-07-23.md`

两个 1h 变体都未通过全部晋级门: 1h 分辨率不改善日线 DVR。永久归档 DVR-1H v1,
不读取 2024, 不调参。
