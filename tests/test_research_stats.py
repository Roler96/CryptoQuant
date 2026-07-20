"""Metrics and statistics.

The statistical functions are checked against cases with known answers, and
against the specific numbers from this project's own audit history.
"""

import math

import numpy as np
import pytest

from cq.core.clock import DAY_MS, HOUR_MS
from cq.core.types import Fill, Side
from cq.research.metrics import (
    YEAR_MS,
    bars_per_year,
    compute_metrics,
    longest_drawdown_ms,
    max_drawdown,
    per_bar_returns,
    sharpe_ratio,
    trades_from_fills,
)
from cq.research.stats import (
    bootstrap_trades,
    compare_with_null,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    sidak_correction,
)

DAY0 = 1_609_459_200_000


def fill(side, quantity, price, ts, fee=0.0):
    return Fill(ts=ts, inst_id="X", side=side, quantity=quantity, price=price, fee=fee)


# ---- annualisation: the sqrt(8760) bug ---------------------------------


def test_annualisation_is_measured_from_the_data():
    hourly = [DAY0 + i * HOUR_MS for i in range(100)]
    four_hourly = [DAY0 + i * 4 * HOUR_MS for i in range(100)]
    daily = [DAY0 + i * DAY_MS for i in range(100)]

    assert bars_per_year(hourly) == pytest.approx(8766.0, rel=1e-3)
    assert bars_per_year(four_hourly) == pytest.approx(2191.5, rel=1e-3)
    assert bars_per_year(daily) == pytest.approx(365.25, rel=1e-3)


def test_a_four_hour_series_is_not_annualised_as_hourly():
    # The exact past defect: 4h results annualised with the hourly factor
    # came out a clean factor of two too large.
    four_hourly = [DAY0 + i * 4 * HOUR_MS for i in range(500)]
    returns = np.full(499, 0.001)

    correct = sharpe_ratio(returns, bars_per_year(four_hourly))
    as_hourly = sharpe_ratio(returns, bars_per_year([DAY0 + i * HOUR_MS for i in range(500)]))

    assert as_hourly / correct == pytest.approx(2.0, rel=1e-3)


def test_one_missing_bar_does_not_shift_the_factor():
    stamps = [DAY0 + i * HOUR_MS for i in range(100)]
    del stamps[50]  # a gap
    assert bars_per_year(stamps) == pytest.approx(8766.0, rel=1e-3)


def test_annualisation_of_a_degenerate_series_is_zero_not_infinite():
    assert bars_per_year([DAY0]) == 0.0
    assert bars_per_year([]) == 0.0


# ---- drawdown ----------------------------------------------------------


def test_max_drawdown_is_measured_peak_to_trough():
    assert max_drawdown([100, 120, 60, 90]) == pytest.approx(0.5)  # 120 -> 60
    assert max_drawdown([100, 110, 120]) == 0.0


def test_longest_underwater_stretch():
    stamps = [DAY0 + i * DAY_MS for i in range(6)]
    # Peak at index 1, recovers only at index 5: four days underwater.
    equity = [100, 120, 80, 90, 110, 130]
    assert longest_drawdown_ms(stamps, equity) == pytest.approx(4 * DAY_MS)


def test_a_curve_that_never_recovers_counts_to_the_end():
    # Otherwise the worst case of all — still underwater when the test ends —
    # would be reported as shorter than a drawdown that recovered.
    stamps = [DAY0 + i * DAY_MS for i in range(5)]
    equity = [100, 120, 80, 70, 60]
    assert longest_drawdown_ms(stamps, equity) == pytest.approx(3 * DAY_MS)


def test_a_monotonically_rising_curve_is_never_underwater():
    stamps = [DAY0 + i * DAY_MS for i in range(4)]
    assert longest_drawdown_ms(stamps, [100, 110, 120, 130]) == 0.0


def test_sharpe_of_a_flat_curve_is_zero_not_undefined():
    assert sharpe_ratio(np.zeros(100), 8766.0) == 0.0


def test_per_bar_returns_handle_a_zero_equity_bar():
    assert per_bar_returns([100.0, 0.0, 0.0]).tolist() == [-1.0, 0.0]


# ---- trade extraction --------------------------------------------------


def test_a_round_trip_becomes_one_trade():
    fills = [
        fill(Side.BUY, 100, 10.0, DAY0, fee=1.0),
        fill(Side.SELL, 100, 12.0, DAY0 + HOUR_MS, fee=1.2),
    ]
    trades = trades_from_fills(fills)

    assert len(trades) == 1
    t = trades[0]
    assert t.side == "long"
    assert t.pnl == pytest.approx(200.0)  # 100 * (12 - 10)
    assert t.fees == pytest.approx(2.2)
    assert t.net_pnl == pytest.approx(197.8)
    assert t.is_win


def test_a_losing_trade_is_marked_as_such():
    fills = [fill(Side.BUY, 100, 10.0, DAY0), fill(Side.SELL, 100, 9.0, DAY0 + HOUR_MS)]
    trade = trades_from_fills(fills)[0]
    assert trade.net_pnl == pytest.approx(-100.0)
    assert not trade.is_win


def test_a_short_round_trip_profits_when_price_falls():
    fills = [fill(Side.SELL, 100, 10.0, DAY0), fill(Side.BUY, 100, 8.0, DAY0 + HOUR_MS)]
    trade = trades_from_fills(fills)[0]
    assert trade.side == "short"
    assert trade.pnl == pytest.approx(200.0)


def test_a_flip_closes_one_trade_and_opens_another():
    fills = [
        fill(Side.BUY, 100, 10.0, DAY0),
        fill(Side.SELL, 200, 12.0, DAY0 + HOUR_MS),  # close long, open short
        fill(Side.BUY, 100, 11.0, DAY0 + 2 * HOUR_MS),
    ]
    trades = trades_from_fills(fills)

    assert [t.side for t in trades] == ["long", "short"]
    assert trades[0].pnl == pytest.approx(200.0)  # 100 * (12 - 10)
    assert trades[1].pnl == pytest.approx(100.0)  # 100 * (12 - 11) short


def test_scaling_into_a_position_averages_the_entry():
    fills = [
        fill(Side.BUY, 100, 10.0, DAY0),
        fill(Side.BUY, 100, 12.0, DAY0 + HOUR_MS),
        fill(Side.SELL, 200, 13.0, DAY0 + 2 * HOUR_MS),
    ]
    trade = trades_from_fills(fills)[0]
    assert trade.entry_price == pytest.approx(11.0)
    assert trade.pnl == pytest.approx(400.0)  # 200 * (13 - 11)


def test_an_open_position_is_not_counted_as_a_trade():
    assert trades_from_fills([fill(Side.BUY, 100, 10.0, DAY0)]) == []


def test_a_partial_exit_closes_only_what_was_sold():
    # Distinguishes "close what the order covers" from "close everything":
    # a flip alone cannot, because there |delta| exceeds the position anyway.
    fills = [
        fill(Side.BUY, 100, 10.0, DAY0),
        fill(Side.SELL, 40, 12.0, DAY0 + HOUR_MS),
    ]
    trades = trades_from_fills(fills)

    assert len(trades) == 1
    assert trades[0].quantity == pytest.approx(40.0)
    assert trades[0].pnl == pytest.approx(80.0)  # 40 * (12 - 10), not 200


def test_the_remainder_of_a_partial_exit_stays_open():
    fills = [
        fill(Side.BUY, 100, 10.0, DAY0),
        fill(Side.SELL, 40, 12.0, DAY0 + HOUR_MS),
        fill(Side.SELL, 60, 13.0, DAY0 + 2 * HOUR_MS),
    ]
    trades = trades_from_fills(fills)

    assert [t.quantity for t in trades] == [pytest.approx(40.0), pytest.approx(60.0)]
    assert trades[1].pnl == pytest.approx(180.0)  # 60 * (13 - 10)


# ---- the best-trade dependency ----------------------------------------


def test_return_excluding_the_best_trade_is_reported():
    # The surviving candidate fell from +1,756% to +330% this way. A headline
    # resting on one trade is a different claim and should not need a
    # follow-up question.
    stamps = [DAY0 + i * DAY_MS for i in range(4)]
    equity = [1000.0, 1000.0, 1000.0, 2000.0]
    fills = [
        fill(Side.BUY, 100, 10.0, DAY0),
        fill(Side.SELL, 100, 10.1, DAY0 + DAY_MS),  # +10
        fill(Side.BUY, 100, 10.0, DAY0 + 2 * DAY_MS),
        fill(Side.SELL, 100, 19.9, DAY0 + 3 * DAY_MS),  # +990
    ]
    m = compute_metrics(stamps, equity, fills, 1000.0)

    assert m.total_return == pytest.approx(1.0)
    assert m.best_trade_pnl == pytest.approx(990.0)
    assert m.return_excluding_best_trade == pytest.approx(0.01)


# ---- bootstrap ---------------------------------------------------------


def test_bootstrap_of_a_uniformly_winning_strategy_never_loses():
    result = bootstrap_trades([0.05] * 20, samples=1000, seed=1)
    assert result.probability_of_loss == 0.0
    assert result.median > 0


def test_bootstrap_finds_loss_probability_a_headline_return_hides():
    # Mostly small losses with one huge win: positive overall, yet most
    # resamples that miss the win end up negative.
    returns = [-0.05] * 19 + [4.0]
    result = bootstrap_trades(returns, samples=5000, seed=1)

    assert result.observed > 0
    assert result.probability_of_loss > 0.2


def test_bootstrap_is_deterministic_for_a_given_seed():
    a = bootstrap_trades([0.1, -0.05, 0.2], samples=500, seed=42)
    b = bootstrap_trades([0.1, -0.05, 0.2], samples=500, seed=42)
    assert a == b


def test_bootstrap_of_no_trades_is_empty_not_an_error():
    assert bootstrap_trades([], samples=100).probability_of_loss == 0.0


# ---- family correction: the p=0.025 -> 0.40 case -----------------------


def test_one_trial_leaves_a_p_value_unchanged():
    assert sidak_correction(0.03, 1) == pytest.approx(0.03)


def test_the_audited_case_reproduces():
    # DogeReflexivityRouterSpot: p=0.0252 alone, ~0.40 across the family of
    # twenty variants that were tried alongside it.
    assert sidak_correction(0.0252, 20) == pytest.approx(0.40, abs=0.01)


def test_correction_grows_with_the_number_of_trials():
    assert sidak_correction(0.01, 5) < sidak_correction(0.01, 50)


def test_correction_rejects_impossible_inputs():
    with pytest.raises(ValueError):
        sidak_correction(1.5, 10)
    with pytest.raises(ValueError):
        sidak_correction(0.05, 0)


# ---- PSR and DSR -------------------------------------------------------


def test_psr_of_a_zero_sharpe_is_a_coin_flip():
    assert probabilistic_sharpe_ratio(0.0, 1000) == pytest.approx(0.5)


def test_psr_rises_with_more_observations():
    few = probabilistic_sharpe_ratio(0.1, 50)
    many = probabilistic_sharpe_ratio(0.1, 5000)
    assert many > few


def test_negative_skew_and_fat_tails_reduce_psr():
    plain = probabilistic_sharpe_ratio(0.1, 1000)
    ugly = probabilistic_sharpe_ratio(0.1, 1000, skew=-1.5, kurtosis=8.0)
    assert ugly < plain


def test_expected_max_sharpe_grows_with_the_number_of_trials():
    # With enough attempts something always looks good; this is that "always".
    assert expected_max_sharpe(2) < expected_max_sharpe(20) < expected_max_sharpe(200)


def test_a_single_trial_needs_no_deflation():
    assert expected_max_sharpe(1) == 0.0


def test_expected_max_sharpe_matches_the_hand_computed_value():
    # Pinned numerically, because the formula has two terms and a monotonic
    # check still passes when one of them is broken.
    #   (1 - 0.5772) * Phi-1(0.95) + 0.5772 * Phi-1(1 - 1/(20e))
    # = 0.4228 * 1.6449 + 0.5772 * 2.0870 = 1.900
    assert expected_max_sharpe(20) == pytest.approx(1.900, abs=0.005)


def test_both_terms_of_the_deflation_benchmark_respond_to_trials():
    # Each term must move; if only one does, deflation is understated.
    # Values cross-checked against an independent transcription of the
    # Bailey & Lopez de Prado formula.
    assert expected_max_sharpe(2) == pytest.approx(0.5198, abs=0.001)
    assert expected_max_sharpe(5) == pytest.approx(1.1926, abs=0.001)
    assert expected_max_sharpe(100) == pytest.approx(2.5306, abs=0.001)


def test_deflating_a_sharpe_by_twenty_trials_moves_it_towards_a_coin_flip():
    # The audited case: PSR 0.976 alone, ~0.50 once twenty trials are counted.
    undeflated = probabilistic_sharpe_ratio(0.062, 1000)
    deflated = deflated_sharpe_ratio(0.062, 1000, trials=20)

    assert undeflated == pytest.approx(0.976, abs=0.002)
    assert deflated == pytest.approx(0.50, abs=0.05), "the documented result"


def test_deflation_does_not_collapse_to_zero_for_every_real_strategy():
    # The default `sharpe_variance` of 1.0 put the benchmark at a per-bar
    # Sharpe of 1.9, which nothing reaches, so the correction returned 0.0 for
    # every input it was ever given. A verdict of "no" that cannot be moved is
    # not a correction; it is a broken instrument that looks like a finding.
    for observations in (250, 1_000, 5_000):
        for sharpe in (0.02, 0.05, 0.10):
            assert deflated_sharpe_ratio(sharpe, observations, trials=20) > 0.0


def test_deflation_still_answers_near_zero_for_a_sharpe_that_is_pure_noise():
    # A zero Sharpe sits 1.9 estimator standard errors below what twenty
    # trials produce by chance, so the deflated confidence is ~3%.
    assert deflated_sharpe_ratio(0.0, 1000, trials=20) < 0.05


def test_more_trials_deflate_further():
    strong = deflated_sharpe_ratio(0.08, 1000, trials=2)
    weak = deflated_sharpe_ratio(0.08, 1000, trials=200)
    assert strong > weak


def test_an_explicit_trial_variance_is_still_honoured():
    # Callers who measured the spread of Sharpes across their own trials
    # should use it; the derived default is only for those who did not.
    assert deflated_sharpe_ratio(
        0.062, 1000, trials=20, sharpe_variance=1.0
    ) == pytest.approx(0.0, abs=1e-9)


# ---- null comparison ---------------------------------------------------


def test_a_result_inside_the_null_is_not_significant():
    rng = np.random.default_rng(0)
    null = rng.normal(0.0, 0.1, 1000)
    comparison = compare_with_null(0.0, null)
    assert comparison.p_value > 0.3


def test_a_result_beyond_the_null_is_significant_until_the_family_is_counted():
    rng = np.random.default_rng(0)
    null = rng.normal(0.0, 0.1, 1000)

    alone = compare_with_null(0.25, null, trials=1)
    in_family = compare_with_null(0.25, null, trials=20)

    assert alone.p_value < 0.05
    assert in_family.family_adjusted_p > alone.p_value
    assert in_family.p_value == alone.p_value, "the raw p-value must not change"


def test_p_value_can_never_be_zero():
    # A finite null cannot prove p=0; the +1 keeps that honest.
    comparison = compare_with_null(999.0, [0.0] * 100)
    assert comparison.p_value > 0
    assert comparison.p_value == pytest.approx(1 / 101)


def test_empty_null_is_an_error_not_a_free_pass():
    with pytest.raises(ValueError):
        compare_with_null(0.5, [])


def test_null_median_is_reported_alongside():
    # A random-entry median that is itself negative is information: it says
    # holding this instrument at random loses money.
    comparison = compare_with_null(0.1, [-0.033] * 100)
    assert comparison.null_median == pytest.approx(-0.033)


# ---- metrics integration -----------------------------------------------


def test_metrics_of_a_flat_run_are_all_zero():
    stamps = [DAY0 + i * HOUR_MS for i in range(10)]
    m = compute_metrics(stamps, [1000.0] * 10, [], 1000.0)

    assert m.total_return == 0.0
    assert m.sharpe == 0.0
    assert m.max_drawdown == 0.0
    assert m.trades == 0
    assert m.win_rate == 0.0


def test_cagr_compounds_over_the_measured_span():
    # Exactly one year, doubling.
    stamps = [DAY0, DAY0 + int(YEAR_MS)]
    m = compute_metrics(stamps, [1000.0, 2000.0], [], 1000.0)
    assert m.cagr == pytest.approx(1.0, rel=1e-3)


def test_profit_factor_is_infinite_when_nothing_lost():
    stamps = [DAY0, DAY0 + HOUR_MS]
    fills = [fill(Side.BUY, 10, 10.0, DAY0), fill(Side.SELL, 10, 11.0, DAY0 + HOUR_MS)]
    m = compute_metrics(stamps, [1000.0, 1010.0], fills, 1000.0)
    assert math.isinf(m.profit_factor)
