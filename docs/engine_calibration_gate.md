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

1. **Forward data.** Genuine out-of-sample bars accrue after the 2026-07-20
   freeze. They adjudicate strategies, not engines, but they do give live and
   backtest something to disagree about.
2. **A different external reference** — a published reference implementation
   with published results, reproduced here.
3. **Paper trading against the live path**, where the same loop runs on the
   same bars through a different broker: a divergence there is an engine
   defect by construction, which is the discrimination this gate lacked.

Option 3 is the strongest and needs no historical baseline at all.

## Reproducing this record

```
uv run python scripts/calibrate_donchian.py
```
