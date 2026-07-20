"""Reports must carry enough provenance to reproduce or discredit a number."""

import numpy as np
import pytest

from cq.context import Series
from cq.core.clock import HOUR_MS
from cq.core.types import CostModel, Intent, MarketSpec
from cq.engine.funding import AssumedFunding, NoFunding
from cq.engine.loop import run_backtest
from cq.research.report import build_report, series_fingerprint
from cq.research.split import Segment, SplitPlan

DAY0 = 1_609_459_200_000
SPOT = MarketSpec("DOGE-USDT", "spot")
SWAP = MarketSpec("DOGE-USDT-SWAP", "swap")


def make_series(closes, inst_id="DOGE-USDT", timeframe="1h", volumes=None):
    n = len(closes)
    values = np.array(closes, dtype=float)
    return Series(
        inst_id=inst_id,
        timeframe=timeframe,
        ts=np.array([DAY0 + i * HOUR_MS for i in range(n)], dtype=np.int64),
        open=values,
        high=values * 1.01,
        low=values * 0.99,
        close=values,
        volume=np.array(volumes if volumes is not None else [100.0] * n, dtype=float),
    )


class Alternating:
    name = "alternating"
    warmup_bars = 1

    def on_bar(self, ctx):
        return Intent(target=1.0 if ctx.index % 4 < 2 else 0.0)


def a_run(series=None, spec=SPOT, funding=None):
    series = series if series is not None else make_series([10, 11, 12, 11, 13, 12, 14, 15])
    return run_backtest(
        Alternating(), series, spec, 1000.0, costs=CostModel(10, 5), funding=funding
    ), series


# ---- data fingerprint --------------------------------------------------


def test_the_same_bars_fingerprint_the_same_way():
    a = make_series([10, 11, 12])
    b = make_series([10, 11, 12])
    assert series_fingerprint(a) == series_fingerprint(b)


def test_a_changed_price_changes_the_fingerprint():
    # Catches "the number cannot be reproduced because a re-sync filled a gap".
    a = make_series([10, 11, 12])
    b = make_series([10, 11, 12.01])
    assert series_fingerprint(a) != series_fingerprint(b)


def test_a_different_range_changes_the_fingerprint():
    assert series_fingerprint(make_series([10, 11, 12])) != series_fingerprint(
        make_series([10, 11])
    )


def test_a_different_instrument_changes_the_fingerprint():
    a = make_series([10, 11, 12], inst_id="DOGE-USDT")
    b = make_series([10, 11, 12], inst_id="BTC-USDT")
    assert series_fingerprint(a) != series_fingerprint(b)


# ---- report contents ---------------------------------------------------


def test_report_states_the_cost_and_funding_assumptions():
    result, series = a_run(spec=SWAP, funding=AssumedFunding(0.0001))
    text = build_report(result, series, bootstrap_samples=100).render()

    assert "10.0 bps fee + 5.0 bps slippage per side" in text
    assert "assumption" in text, "an assumed rate must never read as measured"


def test_funding_off_is_reported_as_an_upper_bound():
    result, series = a_run(spec=SWAP, funding=NoFunding())
    text = build_report(result, series, bootstrap_samples=100).render()
    assert "upper bound" in text


def test_an_uncommitted_tree_is_marked_dirty(monkeypatch):
    # A dirty tree cannot be checked out again, so a result produced from one
    # must not claim the provenance of a clean commit.
    import subprocess

    from cq.research import report as report_module

    class Completed:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return Completed("abc1234\n")
        return Completed(" M cq/engine/loop.py\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert report_module.git_commit() == "abc1234-dirty"


def test_a_clean_tree_reports_the_bare_commit(monkeypatch):
    import subprocess

    from cq.research import report as report_module

    class Completed:
        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: Completed("abc1234\n" if "rev-parse" in cmd else "")
    )
    assert report_module.git_commit() == "abc1234"


def test_report_carries_a_commit_and_a_data_fingerprint():
    result, series = a_run()
    report = build_report(result, series, bootstrap_samples=100)

    assert report.commit
    assert report.data_fingerprint == series_fingerprint(series)
    text = report.render()
    assert report.commit in text
    assert report.data_fingerprint in text


def test_report_repeats_what_a_historical_split_cannot_claim():
    result, series = a_run()
    split = SplitPlan(
        study="donchian",
        segments=(Segment("train", "2021-01-01", "2024-07-01"),),
    )

    text = build_report(result, series, split=split, bootstrap_samples=100).render()

    assert "cannot adjudicate" in text
    assert split.fingerprint in text


def test_unfillable_orders_are_surfaced_not_buried():
    series = make_series([10, 11, 12, 11, 13, 12], volumes=[100, 0, 0, 100, 100, 100])
    result = run_backtest(Alternating(), series, SPOT, 1000.0, costs=CostModel(10, 5))

    text = build_report(result, series, bootstrap_samples=100).render()

    assert "could not be filled" in text


def test_a_clean_run_says_nothing_it_cannot_claim():
    result, series = a_run()
    text = build_report(result, series, bootstrap_samples=100).render()
    assert "What this cannot claim" not in text


def test_report_writes_a_file(tmp_path):
    result, series = a_run()
    path = build_report(result, series, bootstrap_samples=100).write(tmp_path)

    assert path.exists()
    assert path.suffix == ".md"
    assert "alternating" in path.read_text(encoding="utf-8")


def test_metrics_and_bootstrap_appear_in_the_rendered_report():
    result, series = a_run()
    text = build_report(result, series, bootstrap_samples=200, seed=7).render()

    assert "Sharpe" in text
    assert "probability of losing money" in text
    assert "without the best trade" in text


def test_the_report_is_deterministic_for_a_given_seed():
    result, series = a_run()
    first = build_report(result, series, bootstrap_samples=200, seed=7)
    second = build_report(result, series, bootstrap_samples=200, seed=7)
    assert first.bootstrap == second.bootstrap


def test_annualisation_in_the_report_follows_the_data():
    hourly = make_series([10 + i * 0.1 for i in range(50)], timeframe="1h")
    result = run_backtest(Alternating(), hourly, SPOT, 1000.0, costs=CostModel(0, 0))
    report = build_report(result, hourly, bootstrap_samples=100)

    assert report.metrics.bars_per_year == pytest.approx(8766.0, rel=1e-3)
