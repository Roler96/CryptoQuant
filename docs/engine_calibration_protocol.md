# Engine calibration protocol — v2026-07-24.2

> This is an engineering protocol, not a strategy study. It produces no claim
> about profitability and does not calibrate production slippage from OKX demo.

## Scope

Calibration is capability-specific:

- `spot/rebalance` covers the shared event loop, closed-bar clock, spot sizing,
  simulated execution, paper execution, cash/holding accounting and
  target rebalancing;
- `spot/on_entry` remains CLOSED until the live path has an explicit ON_ENTRY
  mode and a deterministic target-transition session is reconciled;
- `swap` additionally requires credentialed demo evidence for contract
  conversion, long/flat/short transitions, position mode and exchange funding
  bills. A spot PASS never opens the swap gate;
- production execution cost remains a separate go-live concern. Demo fees and
  fills are context only.

Every market/sizing scope is CLOSED until its own current artifact passes.
The failed Donchian comparison remains a regression diagnostic, but its
underspecified historical strategy rule is not an alternative way to tune the
new engine.

## Frozen spot instrument

- instrument: `DOGE-USDT` spot;
- timeframe: `5m`;
- strategy: `SpotCalibrationSequence`, which repeats the fixed targets
  `0%, 0%, 20%, 20%, 40%, 40%, 20%, 20%, 0%, 0%`;
- no-trade band: `1%` of equity;
- market decisions consume closed bar `t`; the paper order is sent after that
  close and the simulator models it at `t+1` open;
- funding: `off`;
- source session and time range must be named explicitly. `latest` is
  forbidden;
- the source log, protocol and engine inputs are SHA-256 fingerprinted.

The current constant-mix session with `weight=0.3, band=0.1` may be retained as
diagnostic evidence, but it cannot issue a PASS artifact. The deterministic
sequence is deliberately outside `cq.strategy`, is restricted to OKX demo, and
must not be interpreted as a trading policy.

The frozen session command is:

```
uv run cq paper run --strategy calibration-sequence --new-session \
  --inst DOGE-USDT --tf 5m --max-bars 200
```

`--new-session` ignores older checkpoints but still requires exchange
reconciliation to prove that the demo account is flat before the first order.
The command rejects `--live` before credentials are loaded.

The session takes approximately 16 hours 40 minutes. Every JSONL event freezes
the complete 5m OHLCV bar; reconciliation builds its backtest series directly
from those logged bars because the repository's historical base store is 1h
and must not manufacture a finer series.

## Frozen minimum coverage

A spot artifact is eligible for PASS only when one fixed session supplies all
of the following:

- at least **200 consecutive closed bars**;
- at least **20 non-initial fills**;
- at least **5 post-initial buys** and **5 post-initial sells**;
- at least one no-trade bar inside the configured drift band;
- at least one post-initial trade outside the band;
- no rejected order.

Duration is not a substitute for state coverage. A long session with one entry
and no rebalance remains insufficient.

## Exact checks

Every eligible session must satisfy all of these:

1. timestamps are contiguous and match the frozen timeframe;
2. live fills match both the shared sizing implementation and a separately
   implemented calibration formula;
3. no-trade/trade decisions agree with the band;
4. logged cash and holdings reconcile exactly, allowing only the explicitly
   identified base-fee or quote-fee convention;
5. pre-trade equity equals marked cash plus holdings, and one row's post-trade
   state becomes the next row's pre-trade state;
6. a real backtest covers every logged bar; unavailable or partial comparison
   is a failure;
7. every check above has a Boolean PASS in the artifact. Missing evidence fails
   closed.

The raw demo-vs-model equity gap is reported but is not used to infer production
cost. Any difference must remain attributable to logged demo fill prices and
fee-currency convention; a future same-fill shadow broker should reduce the
unexplained residual to floating-point tolerance before this protocol version
is promoted beyond spot.

## Holdout access

The session runs without inspecting aggregate results. Before the one terminal
reconciliation, create a fixed `forward_holdout` plan and call
`record_holdout_access` with the hypothesis that this named session satisfies
the exact parity and coverage gates. Re-running after seeing a failure is
another recorded access.

## Machine verdict

`scripts/reconcile_paper.py LOG --holdout-end YYYY-MM-DD --artifact
reports/calibration/spot_rebalance.json` writes the only accepted
spot/rebalance artifact. It exits non-zero for insufficient coverage, missing
bar data, any exact mismatch, or an artifact write failure.

The artifact is bound to:

- protocol version;
- capability;
- source-log SHA-256;
- exact bar-series fingerprint and timestamp range;
- calibration checks and evidence;
- content fingerprint of the engine, live path, feed, calibration strategy and
  reconciler.

Research output verifies the artifact against the current source fingerprint.
Any relevant source edit closes the gate until calibration is repeated.

The swap gate stays CLOSED until a separate protocol version and reconciler
cover the swap-only behavior listed above.
