# DLSR Frozen Discovery Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the never-evaluated, pre-registered DOGE 5m downside-liquidity-sweep-reclaim study and execute its frozen discovery protocol without reading any bar at or after `2025-06-01T00:00:00Z`.

**Architecture:** Restore the exact audited strategy and synthetic tests from commit `1718535d8470787b6e3ebf1d9baceb332a42789b`, then add a focused `cq/research/dlsr/` research package. The strategy remains the causal runtime authority; the research package independently extracts the frozen shell/reclaim schedule, simulates fixed schedules, evaluates matched-shell random plans and protocol gates, and proves parity with the engine on synthetic and real explore data.

**Tech Stack:** Python 3.11, NumPy, pandas, SciPy, SQLite through read-only connections, the existing `cq` event loop, pytest, argparse.

## Global Constraints

- The frozen protocol is `docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_PROTOCOL_2026-07-24.md`; if this plan differs, the protocol wins.
- Query only `[2021-01-01T00:00:00Z, 2025-06-01T00:00:00Z)` from `data/cq.db`; never call or reconstruct a forward-holdout accessor.
- Restore DLSR rules from historical commit `1718535`; do not change thresholds, holding periods, cooldown, target weight, costs, or the seven-version family.
- Main cost is `10 bps fee + 5 bps slippage` per side; stress cost is `10 bps fee + 15 bps slippage` per side.
- Every signal uses a closed native 5m bar and executes only at the next contiguous bar open; zero-volume entry bars void the event and gaps invalidate the run.
- Only `main` can advance. Neighbors are stability checks and may not replace it.
- The machine report is `reports/research/dlsr_v1.json`; the human result is `docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_RESULTS_2026-08-03.md`.

---

### Task 1: Restore the frozen audited artifacts

**Files:**
- Create: `cq/strategy/doge_dlsr.py`
- Create: `tests/test_doge_dlsr.py`
- Create: `scripts/dry_run_doge_dlsr.py`
- Create: `docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_PROTOCOL_2026-07-24.md`
- Create: `docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_ENGINEERING_2026-07-24.md`
- Create: `docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_AUDIT_2026-07-24.md`

**Interfaces:**
- Consumes: current `Context`, `Intent`, `MarketSpec`, `Sizing`, and `run_backtest` interfaces.
- Produces: `DogeDlsrConfig`, `FROZEN_VERSIONS`, `FAMILY_TRIALS`, and `DogeDlsr` exactly as stored in commit `1718535`.

- [ ] **Step 1: Recover the six files byte-for-byte from commit `1718535`**

Use a reverse deletion patch limited to the six paths. Do not restore unrelated code from the old research subsystem.

- [ ] **Step 2: Verify the restored source hashes**

Run:

```bash
sha256sum cq/strategy/doge_dlsr.py tests/test_doge_dlsr.py scripts/dry_run_doge_dlsr.py
```

Expected historical hashes:

```text
2e407bd773d268cf0f53a1943f423c367c1233d307b72ec48e09aa87e38dd2de  cq/strategy/doge_dlsr.py
94b12e2aa86f440deb2e5ff0dfc8b726b199c9ae67aaa000dd60b57f4c0cd9a7  tests/test_doge_dlsr.py
8a0d04a4d660991c0eab4e99f11132c6fa15ae2dc76d9068d093e6f0eb018f4d  scripts/dry_run_doge_dlsr.py
```

- [ ] **Step 3: Run the historical synthetic tests before compatibility edits**

Run: `.venv/bin/pytest tests/test_doge_dlsr.py -v`

Expected: either all 25 pass, or failures are limited to deleted public helpers such as `cq.research.split.to_ms`.

- [ ] **Step 4: Make only compatibility edits required by the current public API**

The known compatibility edit is in `scripts/dry_run_doge_dlsr.py`: use `EXPLORE_START` and `FORWARD_FREEZE` integer constants directly instead of importing deleted `to_ms`. Do not change `cq/strategy/doge_dlsr.py` unless a current engine interface makes the historical code fail; any such change requires a focused regression test first.

- [ ] **Step 5: Re-run focused tests and the no-performance dry run**

Run:

```bash
.venv/bin/pytest tests/test_doge_dlsr.py -v
.venv/bin/python scripts/dry_run_doge_dlsr.py
```

Expected: 25 tests pass; the dry run reports the fixed window, 464,256 bars, and completes without printing any performance metric.

- [ ] **Step 6: Commit the recovery**

```bash
git add cq/strategy/doge_dlsr.py tests/test_doge_dlsr.py scripts/dry_run_doge_dlsr.py docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_*.md
git commit -m "research: recover the frozen DLSR candidate"
```

---

### Task 2: Build the frozen data, event, and episode simulator

**Files:**
- Create: `cq/research/dlsr/__init__.py`
- Create: `cq/research/dlsr/data.py`
- Create: `cq/research/dlsr/events.py`
- Create: `cq/research/dlsr/backtest.py`
- Create: `tests/test_dlsr_data.py`
- Create: `tests/test_dlsr_events.py`
- Create: `tests/test_dlsr_backtest.py`

**Interfaces:**
- `load_explore_series(db_path: Path) -> Series`
- `validate_explore_series(series: Series) -> DataIntegrity`
- `scan_candidates(series: Series, config: DogeDlsrConfig) -> CandidateSet`
- `build_schedule(series: Series, candidates: Sequence[Candidate], config: DogeDlsrConfig, evaluation_start_ms: int | None = None, evaluation_end_ms: int | None = None) -> tuple[EpisodePlan, ...]`
- `simulate(series: Series, schedule: Sequence[EpisodePlan], *, fee_bps: float, slippage_bps: float, initial_cash: float = 10_000.0, target_weight: float = 0.25) -> BacktestResult`

- [ ] **Step 1: Write failing data-contract tests**

Cover the exact half-open SQL boundary, native `DOGE-USDT`/`5m` identity, first/last timestamp, 300,000 ms contiguity, finite/legal OHLCV, and fingerprint-before-validation behavior. Include a spy connection or temporary SQLite fixture proving `ts >= FORWARD_FREEZE` is never returned.

- [ ] **Step 2: Run the data tests and confirm the package is missing**

Run: `.venv/bin/pytest tests/test_dlsr_data.py -v`

Expected: FAIL importing `cq.research.dlsr.data`.

- [ ] **Step 3: Implement the read-only data panel**

`load_explore_series` must use a `mode=ro` SQLite URI and parameters `(DOGE-USDT, 5m, EXPLORE_START, FORWARD_FREEZE)`. `DataIntegrity` records row count, first/last timestamp, `series_fingerprint`, zero-volume count, and all integrity booleans; invalid input raises before any signal calculation.

- [ ] **Step 4: Write failing event-extraction tests**

Use the historical DLSR synthetic-bar fixture to assert:

```python
candidate = scan_candidates(series, FROZEN_VERSIONS["main"])
assert candidate.shell_indices == (event_index,)
assert candidate.reclaim_indices == (event_index,)
assert build_schedule(series, candidate.reclaims, FROZEN_VERSIONS["main"])[0].entry_index == event_index + 1
```

Also cover each of the six shell/reclaim gates, zero-volume next-open rejection, delayed zero-volume exit, 144-bar cooldown from actual exit, no replacement events, year cold starts, all seven frozen versions, and an episode that would exit at or beyond the freeze being excluded.

- [ ] **Step 5: Implement causal shell/reclaim extraction and scheduling**

`Candidate` records signal index/time, entry index/time, scheduled and actual exit indexes/times, actual hold bars, year, UTC six-hour bucket, and whether the reclaim geometry passed. Compute baseline medians strictly from `t-2016:t`, the floor from `t-12:t`, and never include `t` in either. `build_schedule` walks candidates in time order, consumes void entries, enforces no overlap and the cooldown from actual exit, and never reads beyond its evaluation end.

- [ ] **Step 6: Prove schedule parity with the runtime strategy**

Add tests that pair engine fills from `run_backtest(DogeDlsr(config), ...)` and compare every entry/exit timestamp with `build_schedule` on the same synthetic series. On the real explore series, compare accepted, voided, and completed counts for all seven versions without calculating returns.

- [ ] **Step 7: Write failing fixed-schedule accounting tests**

Hand-calculate a two-episode path and assert next-open execution, `Sizing.ON_ENTRY` quantity, buy/sell adverse slippage, two fees, 5m mark-to-market equity, flat bars between episodes, episode net return, and final forced close at the last available close for an incomplete episode.

- [ ] **Step 8: Implement the simulator**

For each entry, size `quantity = target_weight * equity_before_entry / entry_open`; buy at `entry_open * (1 + slippage_bps/10_000)` and charge the fee on executed notional. Hold quantity fixed. Sell at `exit_open * (1 - slippage_bps/10_000)` and charge the second fee. Record every 5m close-equity point and normalized episode PnL. An incomplete final position is force-closed at the last close, marked `forced=True`, and excluded from the normal episode count.

- [ ] **Step 9: Prove simulator parity with the current engine**

On synthetic completed episodes and then the real main schedule, require equal fill timestamps and equity within `1e-10` relative tolerance against `run_backtest`, provided neither path ends with an open position.

- [ ] **Step 10: Run focused tests and commit**

```bash
.venv/bin/pytest tests/test_dlsr_data.py tests/test_dlsr_events.py tests/test_dlsr_backtest.py tests/test_doge_dlsr.py -v
git add cq/research/dlsr cq/strategy/doge_dlsr.py tests/test_dlsr_*.py tests/test_doge_dlsr.py
git commit -m "feat(research): build the frozen DLSR event simulator"
```

---

### Task 3: Implement performance, bootstrap, matched-shell null, and gates

**Files:**
- Create: `cq/research/dlsr/stats.py`
- Create: `tests/test_dlsr_stats.py`

**Interfaces:**
- `performance(result: BacktestResult) -> dict[str, float | int]`
- `cold_start_years(series: Series, candidates: CandidateSet, config: DogeDlsrConfig, *, fee_bps: float, slippage_bps: float) -> list[dict[str, object]]`
- `block_bootstrap(daily_returns: pd.Series, *, block_days: int = 28, samples: int = 10_000, seed: int = 20260724) -> dict[str, float | int]`
- `matched_shell_test(series: Series, actual: Sequence[EpisodePlan], shell: Sequence[Candidate], config: DogeDlsrConfig, *, samples: int = 10_000, seed: int = 20260724, family_trials: int = 7) -> dict[str, object]`
- `gate_verdict(...) -> dict[str, bool | int | float | str]`

- [ ] **Step 1: Write failing performance and calendar tests**

Assert total return from the full equity path, max drawdown from all 5m marks, UTC daily returns including zero-event days, Sharpe as `mean(daily)/std(daily)*sqrt(365)`, completed episode count, best-episode suppression without schedule replacement, and independent 2021–2024 cold starts.

- [ ] **Step 2: Implement deterministic performance metrics**

Use simple returns between consecutive UTC day-end equity marks. Best-episode suppression removes that episode's PnL from the frozen schedule and replays the remaining schedule; it does not allow an event blocked by the original cooldown to enter.

- [ ] **Step 3: Write failing bootstrap tests**

Use a tiny deterministic daily series and assert 28-day circular indexing, exactly 10,000 samples, seed reproducibility, compound-return P5, and preservation of zero-event days.

- [ ] **Step 4: Implement the frozen 28-day circular moving-block bootstrap**

Each resample draws circular contiguous 28-day blocks until the original number of UTC days is reached, truncates the excess, compounds with `prod(1+r)-1`, and reports the linear 5th percentile.

- [ ] **Step 5: Write failing matched-shell tests**

Construct shell candidates in exact `(entry year, UTC six-hour bucket, actual hold bars)` strata. Assert that every random plan matches actual stratum counts, samples without replacement, enforces no overlap and the 144-bar cooldown, uses identical costs/weight, rejects whole invalid plans, and computes:

```python
p_raw = (1 + np.count_nonzero(random_stat >= observed_stat)) / 10_001
p_sidak = 1 - (1 - p_raw) ** 7
```

- [ ] **Step 6: Implement the matched-shell random null**

The statistic is mean net episode return normalized by entry notional. Generate exactly 10,000 valid plans or return `powered=False`; never relax a stratum or cooldown requirement. Record the observed statistic, random median/P5/P95, `p_raw`, `p_sidak`, valid/rejected plan counts, and seed.

- [ ] **Step 7: Write and implement all nine frozen gates**

The gates are literal translations of protocol section “发现门”: main economics/Sharpe/MaxDD; stress return; less-best return; total/year sample counts; positive cold-start years; bootstrap P5; matched-shell Sidak; positive neighbors; and integrity/execution semantics. Verdict is `DISCOVERY_PASS` only when all nine are true, otherwise `DISCOVERY_FAIL`; an integrity failure is `INVALID` and takes precedence.

- [ ] **Step 8: Run focused tests and commit**

```bash
.venv/bin/pytest tests/test_dlsr_stats.py tests/test_dlsr_backtest.py tests/test_dlsr_events.py -v
git add cq/research/dlsr/stats.py tests/test_dlsr_stats.py
git commit -m "feat(research): evaluate the frozen DLSR discovery gates"
```

---

### Task 4: Wire the reproducible runner, CLI, and reports

**Files:**
- Create: `cq/research/dlsr/runner.py`
- Create: `tests/test_dlsr_runner.py`
- Modify: `cq/research/commands.py`
- Modify: `tests/test_research_commands.py`
- Create at run time: `reports/research/dlsr_v1.json`
- Create after the run: `docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_RESULTS_2026-08-03.md`

**Interfaces:**
- `run_study(db_path: Path = Path("data/cq.db")) -> dict[str, object]`
- CLI: `cq research dlsr run --database data/cq.db --out reports/research/dlsr_v1.json`

- [ ] **Step 1: Write failing runner-contract tests**

Assert the report contains the study tag, immutable boundaries, data fingerprint/counts, strategy source hash, seven frozen configs, main/stress metrics, four cold-start years, bootstrap details, matched-shell details, less-best result, all nine gates, and verdict. Patch the store/loader to throw if a query can reach `FORWARD_FREEZE`.

- [ ] **Step 2: Implement the runner**

Load and validate once, scan each frozen version once, simulate main and stress, run the pre-registered inference, and return JSON-safe built-in values. Integrity errors return an `INVALID` payload; programming errors propagate.

- [ ] **Step 3: Write failing CLI tests and wire the command**

The command must require an explicit output path, write sorted/indented JSON atomically, print only the output path and verdict, and exit nonzero only for `INVALID` or I/O failure. `DISCOVERY_FAIL` is a valid research outcome and exits zero.

- [ ] **Step 4: Run the frozen discovery exactly once**

Run:

```bash
.venv/bin/cq research dlsr run --database data/cq.db --out reports/research/dlsr_v1.json
```

Do not inspect a partial output to alter any parameter. If `DISCOVERY_FAIL`, record it and move the parent research goal to the next pre-declared candidate; do not open the holdout.

- [ ] **Step 5: Write the human result from the machine authority**

Include verdict, main/stress return/Sharpe/MaxDD, episode counts, all four cold-start years, less-best, bootstrap P5, matched-shell observed/random/Sidak result, seven-version stability, all gates, data fingerprint, execution limitations, and the explicit no-holdout/no-capital decision. If passed, the decision is only to schedule the fixed 2027 holdout/shadow process, never immediate live capital.

- [ ] **Step 6: Run full verification**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check cq tests scripts
.venv/bin/pyright
.venv/bin/cq research dlsr run --database data/cq.db --out /tmp/dlsr_v1_rerun.json
cmp reports/research/dlsr_v1.json /tmp/dlsr_v1_rerun.json
git diff --check
```

Expected: tests/lint/types pass and the rerun is byte-identical.

- [ ] **Step 7: Commit the result**

```bash
git add cq/research/dlsr cq/research/commands.py tests/test_dlsr_runner.py tests/test_research_commands.py reports/research/dlsr_v1.json docs/research/doge-5m/DOWNSIDE_LIQUIDITY_SWEEP_RECLAIM_RESULTS_2026-08-03.md
git commit -m "research: execute the frozen DLSR discovery"
```

---

### Task 5: Continue the parent strategy search if DLSR fails

**Files:**
- Create only after a DLSR failure: `docs/superpowers/specs/2026-08-03-random-maturity-basis-design.md`

- [ ] **Step 1: Preserve the DLSR verdict without tuning**

Close only the exact DLSR v1 mechanism. Do not change `range_mult`, `volume_mult`, hold bars, reclaim geometry, cooldown, or costs based on its result.

- [ ] **Step 2: Start the next independent candidate**

The next design is cost-bound random-maturity spot/perpetual basis convergence, motivated by the no-arbitrage bound and using the existing paired OKX spot/swap histories. It must be pre-registered separately, distinguish itself from the failed fixed-horizon BSR study, and use official historical funding only where coverage exists. This task begins a new spec/plan cycle and is not part of DLSR implementation.
