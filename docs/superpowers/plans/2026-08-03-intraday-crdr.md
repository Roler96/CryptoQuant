# CRDR Intraday Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run the frozen CRDR v1 study that tests six-hour cross-sectional residual reversal across nine OKX perpetual swaps without reading the reserved post-2025-06-01 window.

**Architecture:** Add a focused `cq/research/crdr/` package with immutable data, signal, backtest, statistics, and orchestration boundaries. The runner composes pure functions around the existing `Store`, writes one reproducible JSON report, and does not create a live strategy unless the frozen verdict is `TRADEABLE_LEAD`.

**Tech Stack:** Python 3.11, numpy, pandas, scipy, SQLite through `cq.data.store.Store`, pytest, argparse.

## Global Constraints

- The frozen design at `docs/superpowers/specs/2026-08-03-intraday-crdr-design.md` wins over this plan if they differ.
- Query only `[2021-01-01T00:00:00Z, 2025-06-01T00:00:00Z)`; never read the reserved later window.
- Use BTC-USDT-SWAP only as factor and exactly the nine frozen tradable swaps from the design.
- Main signal is 6h residual reversal with a 720h beta window, causal 90-day 80% dispersion quantile, and checkpoints at 00/08/16 UTC.
- Enter at `c+1h`, exit at `c+7h`, use fixed contracts within an episode, and keep episodes non-overlapping.
- Main cost is 15 bps per side; stress is 25 bps per side plus 5 bps per episode for unknown funding.
- All variants are frozen diagnostics. Never promote a neighbor or ablation over the main candidate.
- Use TDD for every module and commit each independently testable task.

---

### Task 1: Frozen data panel

**Files:**
- Create: `cq/research/crdr/__init__.py`
- Create: `cq/research/crdr/data.py`
- Test: `tests/test_crdr_data.py`

**Interfaces:**
- Consumes: `Store.load_ohlcv(inst_id, "1h", start_ms, end_ms) -> pd.DataFrame`.
- Produces: `StudyPanel`, `fingerprint_frame(frame) -> str`, `load_study_panel(store) -> StudyPanel`.

- [ ] **Step 1: Write the failing contract and alignment tests**

```python
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from cq.research.crdr.data import (
    END_MS,
    START_MS,
    DataContractError,
    fingerprint_frame,
    panel_from_frames,
)


def _frame(start="2021-01-01", periods=4):
    index = pd.date_range(start, periods=periods, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": [1.0] * periods, "high": [1.1] * periods,
         "low": [0.9] * periods, "close": np.arange(1, periods + 1, dtype=float),
         "volume": [10.0] * periods}, index=index
    )


def test_query_boundary_is_frozen():
    assert START_MS == int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert END_MS == int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)


def test_fingerprint_changes_when_volume_changes():
    frame = _frame()
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("volume")] = 11.0
    assert fingerprint_frame(frame) != fingerprint_frame(changed)


def test_panel_keeps_missing_and_degenerate_bars_invalid():
    good = _frame()
    bad = _frame().drop(_frame().index[1])
    bad.loc[bad.index[1], "volume"] = 0.0
    panel = panel_from_frames({"A": good, "B": bad})
    assert panel.valid.loc[good.index[0], ["A", "B"]].all()
    assert not panel.valid.loc[good.index[1], "B"]
    assert not panel.valid.loc[good.index[2], "B"]
    assert np.isnan(panel.opens.loc[good.index[1], "B"])
```

- [ ] **Step 2: Run tests and confirm the import failure**

Run: `.venv/bin/pytest tests/test_crdr_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.crdr'`.

- [ ] **Step 3: Implement the immutable panel and exact data contract**

```python
@dataclass(frozen=True)
class StudyPanel:
    opens: pd.DataFrame
    closes: pd.DataFrame
    valid: pd.DataFrame
    fingerprints: dict[str, str]
    raw_counts: dict[str, int]
    dropped_counts: dict[str, int]


def fingerprint_frame(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for ts, row in frame.sort_index().iterrows():
        digest.update(struct.pack(
            "<qddddd", int(ts.timestamp() * 1000), float(row.open), float(row.high),
            float(row.low), float(row.close), float(row.volume)
        ))
    return digest.hexdigest()[:16]


def load_study_panel(store: Store) -> StudyPanel:
    frames = {
        inst: store.load_ohlcv(inst, "1h", START_MS, END_MS)
        for inst in ALL_INSTRUMENTS
    }
    panel = panel_from_frames(frames)
    mismatches = [inst for inst in ALL_INSTRUMENTS
                  if panel.fingerprints[inst] != EXPECTED_FINGERPRINTS[inst]
                  or panel.raw_counts[inst] != EXPECTED_COUNTS[inst]]
    if mismatches:
        raise DataContractError(f"CRDR frozen data mismatch: {mismatches}")
    return panel
```

`panel_from_frames` must build the complete hourly union index, reindex without filling, retain raw opens/closes, and set valid only when all OHLCV fields are finite, prices are positive, `high > low`, and `volume > 0`.

- [ ] **Step 4: Run the focused tests**

Run: `.venv/bin/pytest tests/test_crdr_data.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cq/research/crdr tests/test_crdr_data.py
git commit -m "feat(research): add frozen CRDR data panel"
```

---

### Task 2: Causal residual-dispersion signals

**Files:**
- Create: `cq/research/crdr/signals.py`
- Test: `tests/test_crdr_signals.py`

**Interfaces:**
- Consumes: `StudyPanel` from Task 1.
- Produces: `SignalConfig`, `SignalEvent`, `generate_signals(panel, config, *, residualized=True, gated=True, continuation=False) -> list[SignalEvent]`.

- [ ] **Step 1: Write failing formula, alignment, gate, and prefix tests**

```python
def test_beta_window_excludes_current_signal_window():
    panel = synthetic_panel(hours=1100, shock_at=1000)
    config = SignalConfig(beta_hours=720, signal_hours=6, dispersion_days=90,
                          dispersion_quantile=0.8, hold_hours=6)
    before = estimate_residuals(panel, panel.opens.index[1000], config)
    changed = mutate_closes(panel, slice(994, 1001), factor=100.0)
    after = estimate_residuals(changed, changed.opens.index[1000], config)
    assert before.betas == pytest.approx(after.betas)
    assert before.residuals != pytest.approx(after.residuals)


def test_gate_excludes_current_dispersion():
    history = pd.Series([1.0] * 270, index=pd.date_range("2021-01-01", periods=270,
                                                        freq="8h", tz="UTC"))
    assert causal_threshold(history, history.index[-1] + pd.Timedelta(hours=8), 90, 0.8) == 1.0


def test_weights_are_neutral_and_continuation_is_exact_inverse():
    reversal = rank_weights(dict(zip(TRADE_INSTRUMENTS, range(9))), continuation=False)
    continuation = rank_weights(dict(zip(TRADE_INSTRUMENTS, range(9))), continuation=True)
    assert sum(reversal.values()) == pytest.approx(0.0)
    assert sum(abs(x) for x in reversal.values()) == pytest.approx(1.0)
    assert continuation == {key: -value for key, value in reversal.items()}


def test_prefix_invariance():
    panel = synthetic_panel(hours=3000)
    prefix = slice_panel(panel, panel.opens.index[2500])
    left = generate_signals(prefix, SignalConfig())
    right = [event for event in generate_signals(panel, SignalConfig())
             if event.checkpoint <= prefix.opens.index[-1]]
    assert left == right
```

Add separate tests for 00/08/16 checkpoints, 250-history minimum, linear quantiles, boundary ties, and rejection when any required beta/signal/entry/exit bar is invalid.

- [ ] **Step 2: Run tests and confirm the missing-module failure**

Run: `.venv/bin/pytest tests/test_crdr_signals.py -v`
Expected: FAIL importing `cq.research.crdr.signals`.

- [ ] **Step 3: Implement signals with explicit frozen types**

```python
@dataclass(frozen=True)
class SignalConfig:
    beta_hours: int = 720
    signal_hours: int = 6
    dispersion_days: int = 90
    dispersion_quantile: float = 0.80
    hold_hours: int = 6


@dataclass(frozen=True)
class SignalEvent:
    checkpoint: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    dispersion: float
    threshold: float | None
    residuals: tuple[tuple[str, float], ...]
    weights: tuple[tuple[str, float], ...]
```

At each frozen checkpoint, require all hourly observations in `[c-726h, c]` plus opens at `c+1h` and `c+1h+hold_hours`. Estimate covariance beta on exactly the 720 returns ending before the signal window. Keep every valid dispersion in causal history; emit an event only when ungated or current dispersion is strictly above the prior 90-calendar-day linear 80% quantile with at least 250 observations.

- [ ] **Step 4: Run signal and data tests**

Run: `.venv/bin/pytest tests/test_crdr_signals.py tests/test_crdr_data.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cq/research/crdr/signals.py tests/test_crdr_signals.py
git commit -m "feat(research): generate causal CRDR signals"
```

---

### Task 3: Fixed-contract episode backtest

**Files:**
- Create: `cq/research/crdr/backtest.py`
- Test: `tests/test_crdr_backtest.py`

**Interfaces:**
- Consumes: `StudyPanel`, `SignalEvent`.
- Produces: `Episode`, `BacktestResult`, `run_backtest(panel, events, *, cost_bps, funding_penalty_bps=0.0) -> BacktestResult`.

- [ ] **Step 1: Write failing hand-calculated tests**

```python
def test_fixed_contract_pnl_and_costs():
    panel = four_asset_episode_panel(entry_prices=[100, 100, 100, 100],
                                     exit_prices=[110, 105, 90, 95])
    event = neutral_event(weights=(0.25, 0.25, -0.25, -0.25), hold_hours=6)
    result = run_backtest(panel, [event], cost_bps=15)
    expected_gross = 0.25 * (0.10 + 0.05 + 0.10 + 0.05)
    assert result.episodes[0].gross_return == pytest.approx(expected_gross)
    assert result.episodes[0].net_return == pytest.approx(expected_gross - 0.003)


def test_stress_cost_is_exactly_55_bps():
    panel = flat_episode_panel()
    result = run_backtest(panel, [neutral_event()], cost_bps=25,
                          funding_penalty_bps=5)
    assert result.episodes[0].net_return == pytest.approx(-0.0055)


def test_hourly_curve_keeps_flat_hours_and_events_do_not_overlap():
    result = run_backtest(long_panel(), two_non_overlapping_events(), cost_bps=15)
    assert len(result.hourly_returns) == len(result.equity)
    assert (result.hourly_returns.loc[flat_hour_index()] == 0.0).all()
    with pytest.raises(ValueError, match="overlap"):
        run_backtest(long_panel(), overlapping_events(), cost_bps=15)
```

Also test leg-level cost allocation, entry/exit timestamps, fixed entry notional rather than hourly rebalancing, and the exact inverse continuation result on the same price path.

- [ ] **Step 2: Run tests and confirm missing implementation**

Run: `.venv/bin/pytest tests/test_crdr_backtest.py -v`
Expected: FAIL importing `cq.research.crdr.backtest`.

- [ ] **Step 3: Implement the event simulator**

```python
@dataclass(frozen=True)
class Episode:
    checkpoint: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    weights: tuple[tuple[str, float], ...]
    gross_return: float
    net_return: float
    long_net_return: float
    short_net_return: float


@dataclass(frozen=True)
class BacktestResult:
    hourly_returns: pd.Series
    equity: pd.Series
    episodes: tuple[Episode, ...]
```

Walk the common hourly index once. At entry, store episode-start equity, entry opens, and fixed contract notionals. For each open-to-open interval add `episode_start_equity * weight * price_change / entry_open`; deduct one side of costs at entry and exit using episode-start equity, split equally between long and short legs, then deduct the episode funding penalty at exit. Reject overlapping events or missing selected-leg opens.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_crdr_backtest.py tests/test_crdr_signals.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cq/research/crdr/backtest.py tests/test_crdr_backtest.py
git commit -m "feat(research): backtest fixed-contract CRDR episodes"
```

---

### Task 4: Metrics, bootstrap, and verdict

**Files:**
- Create: `cq/research/crdr/stats.py`
- Test: `tests/test_crdr_stats.py`

**Interfaces:**
- Consumes: `BacktestResult`.
- Produces: `performance(result) -> dict[str, float]`, `calendar_segments(result) -> list[dict]`, `block_bootstrap(hourly_returns, *, block_days=7, samples=5000, seed=0) -> dict`, `gate_verdict(...) -> dict`.

- [ ] **Step 1: Write failing metric and verdict tests**

```python
def test_metrics_include_inactive_hours():
    returns = pd.Series([0.0, 0.01, 0.0, -0.005], index=hourly_index(4))
    metrics = performance(result_from_returns(returns))
    assert metrics["total_return"] == pytest.approx((1.01 * 0.995) - 1)
    assert metrics["max_drawdown"] == pytest.approx(-0.005)


def test_bootstrap_is_reproducible_and_reports_p5():
    returns = repeated_daily_hourly_returns([0.01, -0.002, 0.006], repeats=100)
    left = block_bootstrap(returns, samples=200, seed=0)
    right = block_bootstrap(returns, samples=200, seed=0)
    assert left == right
    assert 0 <= left["p_value"] <= 1
    assert "annual_return_p5" in left


def test_positive_result_does_not_promote_when_mechanism_fails():
    gates = gate_verdict(main=passing_metrics(), stress=passing_metrics(),
                         segments=passing_segments(), neighbors=passing_neighbors(),
                         bootstrap=passing_bootstrap(), ablations=failed_mechanism(),
                         episodes=passing_episodes())
    assert gates["G6_mechanism"] is False
    assert gates["verdict"] == "MECHANISM_UNSUPPORTED"
```

Add table-driven tests for all five verdicts, 4/5 calendar stability, 5/6 neighbors, 200 total and 20-per-segment sample floors, both-leg gate, delete-best-episode return, and main/stress cost separation.

- [ ] **Step 2: Run tests and confirm missing implementation**

Run: `.venv/bin/pytest tests/test_crdr_stats.py -v`
Expected: FAIL importing `cq.research.crdr.stats`.

- [ ] **Step 3: Implement exact frozen inference**

Aggregate hourly returns to UTC calendar days with `(1+r).prod()-1`, reindex every date in the evaluation span with zeros, and circularly sample seven-day blocks. Center daily returns only for the null p-value; use raw daily returns for annual-return P5. Return JSON-safe Python floats and booleans. Apply verdict precedence `INVALID`, then `CLOSED`, then `TRADEABLE_LEAD`, then `REAL_BUT_SUBTHRESHOLD`, otherwise `MECHANISM_UNSUPPORTED`.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_crdr_stats.py tests/test_crdr_backtest.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cq/research/crdr/stats.py tests/test_crdr_stats.py
git commit -m "feat(research): evaluate CRDR statistical gates"
```

---

### Task 5: Frozen orchestration and CLI

**Files:**
- Create: `cq/research/crdr/runner.py`
- Modify: `cq/research/commands.py`
- Test: `tests/test_crdr_runner.py`
- Test: `tests/test_research_commands.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `run_study(store) -> dict`, CLI `cq research crdr run [--db PATH] [--out PATH]`.

- [ ] **Step 1: Write failing orchestration and CLI tests**

```python
def test_runner_emits_every_frozen_variant(monkeypatch):
    monkeypatch.setattr(runner, "load_study_panel", lambda store: synthetic_realistic_panel())
    report = runner.run_study(object(), bootstrap_samples=50)
    assert report["study_tag"] == "crypto-cross-sectional-residual-dispersion-reversion-v1"
    assert set(report["neighbors"]) == {"signal_4h", "signal_8h", "hold_4h",
                                         "hold_5h", "gate_q70", "gate_q90"}
    assert set(report["ablations"]) == {"raw_reversal", "ungated_residual_reversal",
                                         "residual_continuation"}
    assert report["data"]["end_exclusive"] == "2025-06-01T00:00:00+00:00"


def test_crdr_cli_writes_json(tmp_path, monkeypatch):
    out = tmp_path / "crdr.json"
    monkeypatch.setattr("cq.research.commands._run_crdr_study",
                        lambda args: write_fake_report(args, out))
    assert main(["research", "crdr", "run", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["study_tag"].endswith("v1")
```

Also assert the continuation ablation uses the main event set, all configs remain frozen, JSON contains fingerprints/counts/drop counts/segments/legs/bootstrap/gates, and `run_study` surfaces data-contract failures as `INVALID` without swallowing programming errors.

- [ ] **Step 2: Run tests and confirm failure**

Run: `.venv/bin/pytest tests/test_crdr_runner.py tests/test_research_commands.py -v`
Expected: FAIL because CRDR runner and parser are absent.

- [ ] **Step 3: Implement runner and command**

```python
MAIN_CONFIG = SignalConfig()
NEIGHBORS = {
    "signal_4h": replace(MAIN_CONFIG, signal_hours=4),
    "signal_8h": replace(MAIN_CONFIG, signal_hours=8),
    "hold_4h": replace(MAIN_CONFIG, hold_hours=4),
    "hold_5h": replace(MAIN_CONFIG, hold_hours=5),
    "gate_q70": replace(MAIN_CONFIG, dispersion_quantile=0.70),
    "gate_q90": replace(MAIN_CONFIG, dispersion_quantile=0.90),
}


def run_study(store: Store, *, bootstrap_samples: int = 5000) -> dict:
    panel = load_study_panel(store)
    main_events = generate_signals(panel, MAIN_CONFIG)
    main = run_backtest(panel, main_events, cost_bps=15)
    stress = run_backtest(panel, main_events, cost_bps=25, funding_penalty_bps=5)
    # Run all frozen neighbors and ablations, then call stats.gate_verdict.
    return report
```

CLI output defaults to `reports/research/crdr_v1.json`; use `json.dumps(report, indent=2, default=str)` and end the file with a newline.

- [ ] **Step 4: Run runner, command, and existing research tests**

Run: `.venv/bin/pytest tests/test_crdr_runner.py tests/test_research_commands.py tests/test_commands.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cq/research/crdr/runner.py cq/research/commands.py tests/test_crdr_runner.py tests/test_research_commands.py
git commit -m "feat(research): wire the frozen CRDR study"
```

---

### Task 6: Execute the preregistered study and record the verdict

**Files:**
- Create: `reports/research/crdr_v1.json`
- Create: `docs/research/crypto-intraday/CRDR_RESULTS_2026-08-03.md`

**Interfaces:**
- Consumes: `cq research crdr run` from Task 5 and the frozen local `data/cq.db`.
- Produces: machine-readable evidence and a concise human verdict; no strategy code.

- [ ] **Step 1: Run the exact frozen study once**

Run: `.venv/bin/cq research crdr run --out reports/research/crdr_v1.json`
Expected: exit 0 and `wrote reports/research/crdr_v1.json`.

- [ ] **Step 2: Validate the result schema and frozen provenance**

Run:

```bash
.venv/bin/python -m json.tool reports/research/crdr_v1.json >/dev/null
.venv/bin/python -c "import json; r=json.load(open('reports/research/crdr_v1.json')); assert r['data']['end_exclusive']=='2025-06-01T00:00:00+00:00'; assert len(r['neighbors'])==6; assert len(r['ablations'])==3; print(r['gates']['verdict'])"
```

Expected: JSON validation succeeds and exactly one frozen verdict prints.

- [ ] **Step 3: Write the result document from JSON without changing rules**

The document must contain: verdict; main and stress return/Sharpe/MaxDD; five calendar segments; long and short contributions; bootstrap p/P5; best-episode deletion; six neighbors; three ablations; every G0–G6 value; data fingerprints; limitations around historical dynamic funding; and an explicit `promote`, `shadow only`, or `close` decision matching the JSON.

- [ ] **Step 4: Cross-check every reported number against JSON**

Run a small read-only script that loads the JSON and asserts every numeric literal copied into the Markdown summary. If manual prose introduces a number not present in JSON, remove it or add a machine-derived report field before documenting it.

- [ ] **Step 5: Commit evidence**

```bash
git add -f reports/research/crdr_v1.json
git add docs/research/crypto-intraday/CRDR_RESULTS_2026-08-03.md
git commit -m "research: record the CRDR intraday verdict"
```

---

### Task 7: Full verification

**Files:**
- Modify only if verification exposes an implementation defect; do not alter frozen research parameters.

**Interfaces:**
- Consumes: the complete implementation and result artifacts.
- Produces: fresh verification evidence for handoff.

- [ ] **Step 1: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: all tests PASS with no timeout.

- [ ] **Step 2: Run lint and type checking**

Run: `.venv/bin/ruff check cq tests`
Expected: `All checks passed!`.

Run: `uv run pyright`
Expected: zero errors.

- [ ] **Step 3: Re-run the study to a temporary path and compare bytes**

Run:

```bash
.venv/bin/cq research crdr run --out /tmp/crdr_v1_repro.json
cmp reports/research/crdr_v1.json /tmp/crdr_v1_repro.json
```

Expected: `cmp` exits 0, proving deterministic output.

- [ ] **Step 4: Confirm repository state and commits**

Run: `git status --short && git log -8 --oneline`
Expected: no uncommitted CRDR files; unrelated user files, if any, remain untouched.
