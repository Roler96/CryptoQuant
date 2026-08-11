# DOGE Coherent-Path Exhaustion Reversal — Temporal Challenge Protocol

Date frozen: 2026-08-11
Status: `FROZEN_BEFORE_CHALLENGE_ACCESS`

## 1. Evidence roles

This protocol follows adaptive open exploration on `[2021-01-01T00:00:00Z, 2025-06-01T00:00:00Z)`. The exploration tested 288 broad-family variants and 192 adaptive coherent-path refinements. Those results are searched development evidence, not confirmation.

The one-time temporal challenge is:

- start inclusive: `2025-06-01T00:00:00Z`
- end exclusive: `2026-08-03T06:45:00Z`
- source: native OKX `DOGE-USDT-SWAP` 5m OHLCV in `data/cq.db`
- no BTC, ETH, cross-asset, funding, OI, social, or on-chain inputs

This interval is a mechanism-specific temporal challenge, not pristine universal OOS: other repository studies have inspected the same calendar period under other mechanisms.

## 2. Frozen candidate

Name: Coherent-Path Exhaustion Reversal (CPER)

1. Resample native 5m bars to epoch-anchored 15m bars, `label='left'`, `closed='left'`.
2. At the close of decision bar `t`, read exactly 19 closes `C[t-18:t]` and their 19 base-volume values.
3. Reject the signal if any close is non-finite/non-positive or any volume is non-finite/non-positive.
4. Compute 18 log returns `r_j = log(C_j/C_{j-1})`.
5. Compute path efficiency `E = abs(sum(r_j)) / sum(abs(r_j))`.
6. If `E < 0.78` or `sum(r_j) == 0`, target flat.
7. Otherwise target the opposite direction: `target = -sign(sum(r_j)) * 0.25`.
8. The target emitted after bar `t` fills at bar `t+1` open.
9. Hold the target for 12 complete 15m bars and emit flat after bar `t+12`, filling the exit at bar `t+13` open. Signals while active are ignored. The earliest next signal decision is the exit-open bar close.
10. Do not enter if the fixed exit open is at or beyond the challenge end.

Frozen implementation:

- `cq/research/coherent_path.py`
- SHA-256: `b3d07727193a7fd0901181560ea34d13916738fe7b6176b4d95450e952549b8a`

## 3. Execution and accounting

- shared engine: `cq-engine/1`
- market: linear swap, maximum leverage 1x
- sizing: `ON_ENTRY`
- target absolute weight: 25%
- main costs: 10 bps fee + 5 bps slippage per side
- stress costs: 15 bps fee + 10 bps slippage per side
- funding: off because measured funding does not cover the challenge start; this omission must remain explicit
- daily Sharpe: UTC daily final marked equity, `mean/std(ddof=1)*sqrt(365)`
- MaxDD: every 15m marked-equity point including initial equity
- any rejected order, odd fill count, non-flat terminal portfolio, or non-finite metric makes the challenge `INVALID`

## 4. Frozen gates and order

Run main first.

- `H0 integrity`: exact half-open data bounds, contiguous native 5m bars, valid OHLCV, 0 rejected orders, exactly two fills per episode, final flat.
- `H1 capacity`: at least 20 completed episodes.
- `H2 main economics`: total return `> 0`, daily Sharpe `>= 0.50`, MaxDD `>= -0.20`.
- `H3 directional mechanism`: both long-episode aggregate PnL and short-episode aggregate PnL strictly positive.
- `H4 concentration`: best five positive episodes contribute `< 60%` of total positive episode PnL.
- `H5 cost stress`: 25 bps/side return `> 0`, Sharpe `>= 0.25`, MaxDD `>= -0.20`.

If H0 fails, verdict is `INVALID`. If H1 or H2 fails, later economic gates are `NOT_RUN`. Only H0–H5 all passing yields `TEMPORAL_CHALLENGE_PASS`. A pass approves forward shadow observation only, not capital.

No threshold, window, hold, target, cost, gate, or input may change after challenge results are read. Any future variant is a separately named generation using new forward data.

## 5. Frozen development evidence

Shared-engine development result at 15 bps/side:

- 111 episodes
- return +40.84%
- Sharpe 1.106
- MaxDD -14.01%
- long PnL and short PnL both positive
- best-five positive-PnL concentration 46.19%

At 25 bps/side: return +33.25%, Sharpe 0.938, MaxDD -14.05%.

Development report SHA-256: `1b7093aaf099ade6d174b350f953d5b2ed17387f7bfc6e34a247f0d03c569312`.
