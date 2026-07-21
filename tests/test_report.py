"""Reports must carry enough provenance to reproduce or discredit a number."""

import numpy as np
import pytest

from cq.context import Series
from cq.core.clock import HOUR_MS
from cq.core.types import CostModel, Intent, MarketSpec
from cq.engine.funding import ActualFunding, AssumedFunding, NoFunding
from cq.engine.loop import run_backtest
from cq.research.report import ProvenanceError, build_report, series_fingerprint
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
    if series is None:
        series = make_series([10, 11, 12, 11, 13, 12, 14, 15], inst_id=spec.inst_id)
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


def test_funding_off_is_reported_as_an_omission_in_both_directions():
    result, series = a_run(spec=SWAP, funding=NoFunding())
    text = build_report(result, series, bootstrap_samples=100).render()
    assert "omitted" in text
    assert "upper bound" not in text, "off is only a bound while the position pays"


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
    assert "less the best trade's P&L" in text


def test_the_report_is_deterministic_for_a_given_seed():
    result, series = a_run()
    first = build_report(result, series, bootstrap_samples=200, seed=7)
    second = build_report(result, series, bootstrap_samples=200, seed=7)
    assert first.bootstrap == second.bootstrap


# ---- the report is bound to the run it describes ------------------------


def test_a_report_cannot_be_given_a_different_instrument():
    result, _ = a_run()
    other = make_series([10, 11, 12, 11, 13, 12, 14, 15], inst_id="BTC-USDT")

    with pytest.raises(ProvenanceError, match="did not come from"):
        build_report(result, other, bootstrap_samples=100)


def test_a_report_cannot_be_given_a_different_range():
    result, _ = a_run()
    shorter = make_series([10, 11, 12])

    with pytest.raises(ProvenanceError, match="bars"):
        build_report(result, shorter, bootstrap_samples=100)


def test_a_report_rejects_data_doctored_after_the_run():
    # The core P0 hole: run on data A, edit one later price, hand the reporter
    # a copy that still agrees on instrument, timeframe, length and first
    # timestamp. The old shape-only check accepted it and recorded the doctored
    # copy's fingerprint. The manifest pins the content the run consumed, so the
    # tampered copy is rejected instead of quietly relabelling the result.
    original = make_series([10, 11, 12, 11, 13, 12, 14, 15])
    result, _ = a_run(series=original)

    tampered = make_series([10, 11, 12, 11, 13, 12, 14, 99])  # same shape, first ts
    assert len(tampered) == len(original)
    assert int(tampered.ts[0]) == int(original.ts[0])

    with pytest.raises(ProvenanceError, match="changed after the run"):
        build_report(result, tampered, bootstrap_samples=100)


def test_a_report_can_be_built_straight_from_the_manifest():
    # No series passed: the run's manifest is the authority on what it consumed,
    # so the report needs nothing handed to it after the fact.
    result, series = a_run()
    report = build_report(result, bootstrap_samples=100)

    assert report.data_fingerprint == series_fingerprint(series)
    assert report.data_fingerprint in report.render()


def test_a_doctored_auxiliary_market_is_also_rejected():
    aux = make_series([1, 2, 3, 4, 5, 6, 7, 8], inst_id="BTC-USDT")
    series = make_series([10, 11, 12, 11, 13, 12, 14, 15])
    result = run_backtest(
        Alternating(), series, SPOT, 1000.0, costs=CostModel(10, 5), aux=[aux]
    )

    tampered_aux = make_series([1, 2, 3, 4, 5, 6, 7, 99], inst_id="BTC-USDT")
    with pytest.raises(ProvenanceError, match="did not come from"):
        build_report(result, series, aux=[tampered_aux], bootstrap_samples=100)


def test_a_split_that_does_not_contain_the_run_is_called_out():
    # The failure this prevents: labelling a 2021 backtest with a forward
    # holdout that begins in 2026, and having the report state in its own
    # words that the result was out-of-sample.
    result, series = a_run()
    forward = SplitPlan(
        study="donchian",
        segments=(Segment("forward", "2026-07-20", "2026-08-01", role="holdout"),),
    )

    text = build_report(result, series, split=forward, bootstrap_samples=100).render()

    assert "no segment" in text
    assert "do not apply" in text


def test_a_split_that_does_contain_the_run_is_not_flagged():
    result, series = a_run()
    split = SplitPlan(
        study="donchian", segments=(Segment("train", "2021-01-01", "2024-07-01"),)
    )

    text = build_report(result, series, split=split, bootstrap_samples=100).render()

    assert "no segment" not in text


def test_auxiliary_markets_must_be_declared_and_are_fingerprinted():
    aux = make_series([1, 2, 3, 4, 5, 6, 7, 8], inst_id="BTC-USDT")
    series = make_series([10, 11, 12, 11, 13, 12, 14, 15])
    result = run_backtest(
        Alternating(), series, SPOT, 1000.0, costs=CostModel(10, 5), aux=[aux]
    )

    # A run that read a second series cannot be reproduced from the primary.
    with pytest.raises(ProvenanceError, match="auxiliary"):
        build_report(result, series, bootstrap_samples=100)

    text = build_report(result, series, aux=[aux], bootstrap_samples=100).render()
    assert series_fingerprint(aux) in text


def test_the_funding_input_is_fingerprinted_not_just_labelled():
    # Two runs with different measured rates must not share provenance.
    series = make_series([10, 11, 12, 11, 13, 12, 14, 15], inst_id="DOGE-USDT-SWAP")
    rates = {DAY0 + i * 8 * HOUR_MS: 0.0001 for i in range(4)}
    other = dict(rates)
    other[DAY0] = 0.05

    def text_for(model):
        result = run_backtest(
            Alternating(), series, SWAP, 1000.0, costs=CostModel(10, 5), funding=model
        )
        return build_report(result, series, bootstrap_samples=100).render()

    assert text_for(ActualFunding(rates, "DOGE-USDT-SWAP")) != text_for(
        ActualFunding(other, "DOGE-USDT-SWAP")
    )


# ---- robustness measures the portfolio ----------------------------------


def test_bootstrap_measures_the_account_not_the_trade_notional():
    # A trade held at half weight that doubles moves the account by +50%.
    # Resampling its own +100% describes a portfolio nobody held.
    class HalfWeight:
        name = "half"
        warmup_bars = 1

        def on_bar(self, ctx):
            return Intent(target=0.5 if ctx.index < 4 else 0.0)

    series = make_series([10, 10, 20, 20, 20, 20])
    result = run_backtest(HalfWeight(), series, SPOT, 1000.0, costs=CostModel(0, 0))
    report = build_report(result, series, bootstrap_samples=100)

    assert report.bootstrap.observed == pytest.approx(0.5, abs=0.02)


def test_a_position_still_open_at_the_end_is_in_the_bootstrap():
    # A run ending 50% down on an open position used to report a 0%
    # probability of loss, because no round trip had completed.
    class BuyAndHold:
        name = "hold"
        warmup_bars = 1

        def on_bar(self, ctx):
            return Intent(target=1.0)

    series = make_series([10, 10, 8, 6, 5, 5])
    result = run_backtest(BuyAndHold(), series, SPOT, 1000.0, costs=CostModel(0, 0))
    report = build_report(result, series, bootstrap_samples=200)

    assert report.bootstrap.observed < 0.0
    assert report.bootstrap.probability_of_loss == pytest.approx(1.0)


def test_a_loss_taken_entirely_in_funding_shows_up_in_the_bootstrap():
    # Entry and exit at the same price: the trade's own return is zero and the
    # account's is not, because funding is charged to the account.
    series = make_series([10] * 26, inst_id="DOGE-USDT-SWAP")

    class HoldThroughFunding:
        name = "holder"
        warmup_bars = 1

        def on_bar(self, ctx):
            return Intent(target=1.0 if ctx.index < 24 else 0.0)

    result = run_backtest(
        HoldThroughFunding(),
        series,
        SWAP,
        1000.0,
        costs=CostModel(0, 0),
        funding=AssumedFunding(0.01),
    )
    report = build_report(result, series, bootstrap_samples=100)

    assert result.portfolio.funding_paid > 0
    assert report.bootstrap.observed < 0.0, "funding cost must reach the bootstrap"


def test_annualisation_in_the_report_follows_the_data():
    hourly = make_series([10 + i * 0.1 for i in range(50)], timeframe="1h")
    result = run_backtest(Alternating(), hourly, SPOT, 1000.0, costs=CostModel(0, 0))
    report = build_report(result, hourly, bootstrap_samples=100)

    assert report.metrics.bars_per_year == pytest.approx(8766.0, rel=1e-3)
