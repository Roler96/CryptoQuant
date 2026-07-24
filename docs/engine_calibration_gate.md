# Engine calibration gate — FAILED (2026-07-20)

> **This is an engine record, not a research result.** No claim is made here
> about whether any strategy makes money. The gate is closed: per the rebuild
> plan, no research conclusions are produced downstream of M4 until an
> external calibration point is available.

## What the gate is for

The rebuilt engine has no external reference. Every internal check can only
show that it is self-consistent, and the previous system was self-consistent
and wrong — its backtests were inflated 25x by a lookahead in the exit path,
and nothing internal caught it. So the plan required one comparison against a
number produced by different code: the DogeDonchianTrend baseline recorded
before the rebuild.

Baseline, from long-term memory (the study document itself was removed from
the repo and lives only in git history):

    DOGE-USDT-SWAP 4h, 120/60 symmetric, 2021-01-01 .. 2026-07-12, 15 bps/side
    +1,747% / Sharpe 0.69 / MaxDD 77.8% / 54 trades

## Result

Reimplemented from the parameters alone — the previous implementation was
deliberately not read — the engine produces:

| | rebuilt engine | baseline |
|---|---|---|
| return | +1,052.8% | +1,747% |
| Sharpe | 0.90 | 0.69 |
| MaxDD | 90.5% | 77.8% |
| trades | 52 | 54 |
| without best trade | +228.1% | +330% |

Funding is off in both, matching the baseline's cost basis. The gate is
**not** passed: the return differs by a factor of 1.6.

## What the gate found on the way

The first run produced **2,138 trades** against the baseline's 54. That was a
real defect, and fixing it is the gate's one unambiguous success.

`Intent.target` is a weight of equity, and the engine re-derived the quantity
every bar to hold that weight constant. For a trend follower this is the wrong
convention and an expensive one: it trims the position as it moves in favour
and adds as it moves against. Sizing is now explicit (`Sizing.ON_ENTRY` vs
`Sizing.REBALANCE`), defaulting to sizing once when the target changes. On
this run the two conventions differ by 54 trades versus 2,138 and +1,053%
versus +390% — the choice is a strategy decision, not an implementation
detail, and it is now recorded in every report.

## Why this is not evidence the engine is broken

The remaining gap is more consistent with a strategy-rule difference than an
engine defect:

- trade count matches within 2 of 54, so entry and exit fire at nearly the
  same moments;
- results are dominated by a handful of trades (best single trade +331%, in
  the 2021 move), so an entry or exit differing by one or two bars compounds
  into a large total difference;
- the engine's arithmetic is verified independently of Donchian: buy-and-hold
  over 12,157 real bars reconciles to the price ratio with zero difference to
  eight decimal places, a ten-bar scenario reconciles by hand, and 19
  deliberate defects in the engine turn the test suite red.

The rule was reimplemented from one line of description — "120/60 4h
long/short symmetric" — which does not determine whether entries trigger on
close or high, whether the exit channel includes the current bar, or whether a
closed position may reverse immediately.

## Why it is recorded as failed anyway

Because the gate cannot tell the two apart, and a gate that cannot
discriminate must not be marked passed. Recovering the exact rule from the
retained study document was considered and declined: the rebuild does not
consult the previous work, and weakening that for one number would cost more
than the number is worth.

Tuning the reimplementation until it matched was never an option. Fitting a
rule to a target figure produces agreement that means nothing.

## What would open the gate

The executable acceptance criteria are now frozen separately in
[`docs/engine_calibration_protocol.md`](engine_calibration_protocol.md).
Passing evidence is capability-specific: a spot result cannot open swap
research, and any relevant source change invalidates the artifact.

1. **Forward data.** Genuine out-of-sample bars accrue after the 2026-07-20
   freeze. They adjudicate strategies, not engines, but they do give live and
   backtest something to disagree about.
2. **A different external reference** — a published reference implementation
   with published results, reproduced here.
3. **Paper trading against the live path**, where the same loop runs on the
   same bars through a different broker: a divergence there is an engine
   defect by construction, which is the discrimination this gate lacked.

Option 3 is the strongest and needs no historical baseline at all. Its current
protocol covers only `spot/rebalance`; it cannot authorize `spot/on_entry` or
any swap result.

### The instrument for option 3: constant-mix, not Donchian

Donchian is a poor cross-check subject for the same reason it was a poor
calibration subject: its result hangs on the exit and reversal semantics this
gate could not pin down, so a paper-vs-backtest gap could be blamed on rule
ambiguity rather than the engine. The 2026-07-22 volatility-harvest study
produced a better instrument — `DogeConstantMix` (frozen in
`cq/strategy/doge_constant_mix.py`). Its equity is a path integral over the
whole run, not a handful of trades whose entry can slip a bar; it makes no
forecast; and, crucially, the live path already sizes every bar, so it *is*
`Sizing.REBALANCE` by construction — the band is the broker's `dust_fraction`
in both places. Backtest and paper therefore run the same semantics with no
disputed rule between them, and any divergence beyond the known
close-vs-next-open sizing price is an engine defect outright.

It is now paper-runnable:

```
cq paper run --strategy constant-mix --weight 0.3 --band 0.1 --inst DOGE-USDT --tf 1h
```

Opening the `spot/rebalance` scope this way requires a demo session to accrue
the frozen event coverage and a script that reconciles its explicitly named
JSONL log against a backtest over the same bars. The reconciler is
`scripts/reconcile_paper.py`; the first session below predates the frozen
coverage threshold and remains diagnostic only.

### First reconcile result (2026-07-23)

`scripts/reconcile_paper.py` on the first constant-mix demo session
(`logs/paper/DOGE-USDT_1h_20260722T112312Z.jsonl`, `doge-cmix-w0.3-b0.1`, 15
closed 1h bars, one entry then a hold) — **RECONCILED**:

- **Decision parity (exact):** feeding each bar's live pre-trade state through
  the backtest's own `target_delta` reproduced every live order — 15/15 bars,
  0 mismatches. The live and backtest sizing are provably the same code.
- **Accounting (exact):** logged post-trade holding and cash follow from the
  fill on all bars. It surfaced one real convention gap: OKX charged the spot
  buy fee in **base coin** (≈305 fewer DOGE), while the sim models the fee as a
  quote-cash deduction and keeps full base. Same equity hit, different split.
- **Band semantics (exact):** 0 bars held past the weight-drift band.
- **Demo execution (context only):** demo slippage +5.51 bps and fee 10.00 bps.
  These are **OKX demo figures, not production** — the demo runs a separate
  simulated book, so they do not calibrate real execution cost and are not
  claimed to. Real slippage stays an unknown to be bounded pessimistically.
- **Backtest equity parity:** a real `run_backtest` over the same production
  bars, seeded at the session's opening equity, tracked the live equity to a
  **max per-bar relative difference of 0.0018%** (live final 73,889.25 vs
  backtest 73,890.40). The decision half of this is a real code check; the
  residual gap is demo fill price vs the modelled fill, not a production number.

**What this establishes, and what it does not.** OKX demo fills and prices differ
from production by construction, so this is a **code-vs-code** cross-check, not a
market-realism one. It establishes the engine faithfulness the gate lacked: the
live path (CCXT/OKX) and the backtest (SimBroker) — genuinely different code —
produce identical decisions, accounting and band behaviour on the same public
production bars, with no divergence attributable to the engine. It does **not**
establish that the cost model matches real execution (demo fills are not real
fills), and it says nothing about the Donchian-baseline discrepancy (1,052.8% vs
1,747%, pre-rebuild code and an ambiguous rule). The question remains
unresolved and the gate stays **CLOSED**:
15 bars with a single rebalance is a thin code cross-check, and production cost
realism remains outside what demo can prove. Option 3's tooling is nonetheless
proven and passing on the axis it can speak to. One real modelling gap it
surfaced — the base-currency spot fee — is an accounting convention worth
confirming against production/OKX docs before it is modelled, not assumed from
demo. Any terminal re-run must name the log and fixed exclusive holdout end,
then record the access, as specified by
`docs/engine_calibration_protocol.md`.

## Reproducing this record

```
uv run python scripts/calibrate_donchian.py
```

The script compares each figure against the baseline within a stated
tolerance and **exits non-zero while the gate is closed**. It previously
printed `GATE: FAILED` and exited 0, so anything chained after it — a shell
`&&`, a cron job, a CI step — read the closed gate as a pass.
