# Paper trading — pending work (opened 2026-07-21)

> **This is an engineering backlog, not a go-live checklist.** The spot pipe
> exists and is proven against OKX demo, but it runs under a placeholder probe.
> No strategy has passed the calibration gate, so nothing here implies the
> system is ready to trade a real view — see `docs/engine_calibration_gate.md`.

## What already works

`cq/live/` drives one live path end to end: `LiveFeed` closed bars →
strategy → `LiveBroker` market order on OKX demo → reconcile against the
exchange → JSONL session log. Spot only, market orders only, target-only.
Sizing is shared with the backtest (`cq/engine/sizing.py::target_delta`), so a
paper order is the one the backtest assumed.

Everything below is what the pipe deliberately does **not** yet do.

## Backlog

### 1. Protective exits → resting exchange orders (correctness parity)
- [ ] Translate `Intent.stop_loss` / `Intent.take_profit` into OKX conditional
      (algo) orders, placed and cancelled alongside the target.

The backtest triggers stops and take-profits intrabar from a bar's high/low.
The live broker ignores them entirely today. **A strategy that relies on a
stop is executed more loosely live than the backtest modelled it** — the single
most dangerous gap here, because it makes live quietly worse than the vetted
result rather than merely different. Must close before any stop-using strategy
runs on the pipe.

### 2. Swap support (DOGE-USDT-SWAP)
- [ ] Position mode (net vs long/short) and leverage set explicitly, not
      inherited from account defaults.
- [ ] Contract-size conversion: OKX swaps trade in contracts, not base coins;
      `target_delta` sizes in base and must be mapped through the multiplier.
- [ ] Funding and liquidation are exchange-side events — reconcile them into
      the session's accounting instead of the sim's modelled funding/liq.
- [ ] `to_symbol` / `spec_from_market` extended past the spot `BASE-QUOTE`
      assumption (swap is `DOGE/USDT:USDT`).

This is the actual research target (perp + funding), and it exercises the
engine's hardest-won semantics. Larger than everything else combined.

### 3. Restart-time reconciliation (crash recovery)
- [ ] On start, rebuild the session's notion of position and cost basis from
      the exchange (the source of truth) and the last JSONL log, so a restart
      mid-position does not double-trade or lose track of an open stop.

`run_paper` currently assumes a clean start and `HeartbeatProbe.reset()` zeroes
its counter. A real strategy carrying state needs its state reconstructed, not
reset, after a crash.

### 4. Idempotent client order ids
- [ ] Attach a deterministic `clOrdId` per (bar, intent) so a retry after a
      network timeout cannot place the same order twice.

The retry wrapper in `OkxTradeClient._call` can resend a create that already
reached the venue. Harmless for reads, a duplicate fill for orders.

### 5. Feed and connection resilience
- [ ] Survive a poll that raises (network blip) without ending the session.
- [ ] Detect and surface a stalled feed (no new closed bar well past when one
      was due) rather than sleeping silently forever.

### 6. Warmup beyond one page (only if a strategy needs it)
- [ ] Page history back for strategies whose `warmup_bars` exceeds the ~100
      bars a single priming poll returns; the probe needs one, so this is
      deferred until a real strategy demands it.

## Suggested order

1 first (it is a correctness gap, not a feature), then 3–5 as a hardening pass
before 2, since swap is where a real strategy would eventually run and it
should land on a pipe that already recovers and de-duplicates. 6 only on demand.
