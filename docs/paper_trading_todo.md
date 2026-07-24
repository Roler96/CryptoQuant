# Paper trading — pending work (opened 2026-07-21)

> **This is an engineering backlog, not a go-live checklist.** The spot pipe
> exists and is proven against OKX demo, but transport completion alone does
> not imply that a strategy is ready for real capital.

## What already works

`cq/live/` drives one live path end to end: `LiveFeed` closed bars →
`LiveEngineFeed` causal contexts → the shared `run_event_loop` → the OKX broker
adapter → reconcile against the exchange → JSONL session log. Backtest and live
therefore share strategy scheduling as well as base-equivalent sizing
(`cq/engine/sizing.py::target_delta`); only feed and broker implementations
differ. The OKX boundary converts swaps to contracts. Targets use market orders
and protective exits use market-on-trigger OKX conditional/OCO algos.
Versioned, fsynced JSONL
checkpoints allow a stopped process to resume when its last processed bar still
matches the exchange. Target, protection, restoration and recovery creates
carry stable client order ids derived from their closed-bar intent. Transient
market-data poll failures are retried without losing the feed high-water mark,
while a successfully connected but stale feed fails explicitly after a
configurable grace period.

Unchecked work below is what the pipe deliberately does **not** yet do.

## Backlog

### 1. Protective exits → resting exchange orders (correctness parity)
- [x] Translate `Intent.stop_loss` / `Intent.take_profit` into OKX conditional
      (algo) orders, placed and cancelled alongside the target.

Implemented 2026-07-21. A single level uses `conditional`; stop plus target uses
`oco` so OKX cancels the other leg after one triggers. The broker cancels the
old algo before a target trade, reconciles the actual post-trade holding, and
places the replacement for that quantity. An uncertain or rejected target
trade restores the previous levels around any remaining holding. The session
log records algo id, size and both levels for later restart recovery. Native
request and lifecycle behavior are covered by deterministic tests; this change
did not place credentialed demo orders.

### 2. Swap support (DOGE-USDT-SWAP)
- [x] Position mode (net vs long/short) and leverage set explicitly, not
      inherited from account defaults.
- [x] Contract-size conversion: OKX swaps trade in contracts, not base coins;
      `target_delta` sizes in base and must be mapped through the multiplier.
- [x] Funding and liquidation are exchange-side events — reconcile them into
      the session's accounting instead of the sim's modelled funding/liq.
- [x] `to_symbol` / `spec_from_market` extended past the spot `BASE-QUOTE`
      assumption (swap is `DOGE/USDT:USDT`).

Implemented 2026-07-21. `cq paper run` accepts `BASE-QUOTE-SWAP` plus explicit
`--leverage` and `--margin-mode`; startup requires Futures or Multi-currency
margin, enforces net position mode, and confirms the requested fixed leverage
before any order can leave the process. Spot-only and Portfolio-margin accounts
fail closed because they cannot satisfy those semantics. Only linear swaps
settled in their quote currency are accepted. Engine quantities remain signed
base-equivalent units; market metadata supplies the contract multiplier used
for order, fill, pending algo, position, lot and minimum-size conversion.

Swap reconciliation reads the signed net position, exchange average/mark/
liquidation prices, settlement cash and exchange equity. Long protection sells;
short protection buys; both are explicitly net, reduce-only algos in the chosen
margin mode. Funding, liquidation and ADL bills retain OKX's signed balance
change and are appended to the durable session event. Each checkpoint also
stores the last queried exchange-time cursor, so restart resumes the bill
interval without treating the simulator's funding or liquidation model as
live truth.

Native request construction, contract conversion, long/short recovery and bill
logging are covered by deterministic tests. This implementation did not place
credentialed demo orders. The only bundled paper strategy remains the plumbing
probe, so completing the swap transport does not make the system ready for
real-money trading.

### 3. Restart-time reconciliation (crash recovery)
- [x] On start, rebuild the session's notion of position and cost basis from
      the exchange (the source of truth) and the last JSONL log, so a restart
      mid-position does not double-trade or lose track of an open stop.

Implemented 2026-07-21. Every event now durably checkpoints post-trade holdings,
cash, average entry, strategy identity/configuration/state, and the active algo.
Startup reads the newest complete JSONL row (including recovery from a torn
tail), reconciles it with OKX balances and both pending `conditional`/`oco`
lists, then adopts the verified algo or rebuilds one whose logged predecessor
is confirmed canceled/failed. Unknown algos, wrong quantities, unexplained
positions, incompatible strategy configuration, and triggered-but-unsettled
orders all fail closed. `HeartbeatProbe` and `DonchianTrend` implement explicit
snapshot/restore contracts, so `reset()` no longer destroys carried state on a
valid resume.

A restart that missed one or more closed bars refuses to continue rather than
silently running stale strategy state. Historical decision replay remains a
separate extension if longer outages must resume automatically.

### 4. Idempotent client order ids
- [x] Attach a deterministic `clOrdId` per (bar, intent) so a retry after a
      network timeout cannot place the same order twice.

Implemented 2026-07-21. Each target, protection, restoration and restart
recovery create receives a stable, role-separated positive-int64 id derived
from the instrument, closed-bar timestamp and intent. Market orders use
`clOrdId`; conditional/OCO orders use `algoClOrdId`; both ids are preserved in
the durable event log.

Create endpoints are now single-shot. After an ambiguous transient failure the
client polls OKX's order-detail endpoint by client id and continues only when
the matching instrument/order is visible. It never resends the create; an
unresolved result raises explicitly as unknown. Protective lookup also requires
the recovered algo to remain `live`, so an older canceled order with the same
id cannot be adopted. Restart-time protection rebuilding uses its own stable id
and can adopt a replacement that survived a second process crash. Deterministic
tests cover successful lookup, unresolved timeout, historical-order rejection
and the no-resend invariant; no credentialed demo order was placed.

### 5. Feed and connection resilience
- [x] Survive a poll that raises (network blip) without ending the session.
- [x] Detect and surface a stalled feed (no new closed bar well past when one
      was due) rather than sleeping silently forever.

Implemented 2026-07-21. Startup priming and the running iterator now retry
ccxt's transient transport failures at the configured poll interval, preserving
the last-emitted timestamp and logging both failures and recovery. A failed
request is never interpreted as an empty successful page, so startup cannot
accidentally arm itself without a real high-water mark.

Every successful poll also checks the next expected close derived from the last
emitted bar and the canonical timeframe duration. If no newer closed bar is
visible after the default 120-second grace (`cq paper run --stall-grace`), the
feed raises a dedicated error; the paper CLI reports it and exits nonzero rather
than sleeping forever. Tests use injected clocks, sleeps and scripted failures,
so this change made no external API or credentialed demo calls.

### 6. Warmup beyond one page (only if a strategy needs it)
- [ ] Page history back for strategies whose `warmup_bars` exceeds the ~100
      bars a single priming poll returns; the probe needs one, so this is
      deferred until a real strategy demands it.

## Suggested order

Items 1–5 are implemented. Item 6 remains deferred until a real strategy needs
more than one page of warmup.
