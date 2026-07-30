import numpy as np
import pytest
from scipy import stats as scipy_stats

from cq.research.coordinate_diagnostics import (
    SIDAK_ALPHA,
    _aggregate_returns,
    combine_scales,
    delta_paired_null_draws,
    delta_r_squared,
    direction_hit_rate,
    evaluate_gates,
    excess_kurtosis,
    paired_null_draws,
    rank_autocorrelation,
    rank_predictive_power,
    select_block_length,
    stationary_bootstrap_indices,
    variance_ratio,
)
from cq.research.dollar_clock import bucket_edges, solve_bucket_size


def test_rank_autocorrelation_detects_a_planted_reversal():
    rng = np.random.default_rng(0)
    noise = rng.normal(0.0, 1.0, 4000)
    reverting = np.empty_like(noise)
    reverting[0] = noise[0]
    for i in range(1, noise.size):
        reverting[i] = noise[i] - 0.5 * reverting[i - 1]
    assert rank_autocorrelation(reverting, lag=1) < -0.2


def test_rank_autocorrelation_is_near_zero_on_iid_noise():
    rng = np.random.default_rng(1)
    assert abs(rank_autocorrelation(rng.normal(0.0, 1.0, 20_000), lag=1)) < 0.03


def test_rank_autocorrelation_is_immune_to_a_single_outlier():
    """The whole reason the main criterion is non-parametric: DOGE's right tail."""
    rng = np.random.default_rng(2)
    clean = rng.normal(0.0, 1.0, 5000)
    contaminated = clean.copy()
    contaminated[2500] = 1e6
    before = rank_autocorrelation(clean, lag=1)
    after = rank_autocorrelation(contaminated, lag=1)
    assert abs(after - before) < 0.01


def test_hit_rate_drops_zero_returns_and_reports_how_many():
    returns = np.array([1.0, 1.0, 0.0, 1.0, -1.0])
    # 样本对 (t, t+1): (1,1) 同号, (1,0) 丢, (0,1) 丢, (1,-1) 异号
    result = direction_hit_rate(returns)
    assert result.pairs == 2
    assert result.dropped == 2
    assert result.rate == pytest.approx(0.5)


def test_hit_rate_is_one_for_perfectly_persistent_signs():
    assert direction_hit_rate(np.array([1.0, 2.0, 3.0, 4.0])).rate == pytest.approx(1.0)


def test_rank_predictive_power_finds_a_planted_link():
    rng = np.random.default_rng(4)
    feature = rng.normal(0.0, 1.0, 5000)
    forward = -0.4 * feature + rng.normal(0.0, 1.0, 5000)
    assert rank_predictive_power(feature, forward) < -0.25


def test_rank_predictive_power_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        rank_predictive_power(np.zeros(5), np.zeros(4))


def test_hit_rate_drops_nan_returns_and_reports_how_many():
    """NaN carries no direction, so NaN pairs are dropped like zero pairs."""
    returns = np.array([np.nan, 1.0, 1.0, -1.0, 1.0])
    # 样本对 (t, t+1): (nan,1) 丢, (1,1) 同号, (1,-1) 异号, (-1,1) 异号
    result = direction_hit_rate(returns)
    assert result.pairs == 3
    assert result.dropped == 1
    assert result.rate == pytest.approx(1.0 / 3)


def test_hit_rate_pairs_dropped_invariant():
    """Invariant: pairs + dropped == len(returns) - 1 holds across various inputs."""
    test_cases = [
        np.array([1.0, 1.0, 1.0, 1.0]),  # all same sign
        np.array([1.0, -1.0, 1.0, -1.0]),  # alternating
        np.array([0.0, 0.0, 0.0, 0.0]),  # all zeros
        np.array([1.0, 0.0, 1.0, 0.0]),  # mixed with zeros
        np.array([np.nan, 1.0, -1.0, 1.0]),  # mixed with NaN
        np.array([1.0, np.nan, -1.0, np.nan]),  # multiple NaNs
        np.array([0.0, np.nan, 1.0, -1.0]),  # both zeros and NaNs
    ]
    for returns in test_cases:
        result = direction_hit_rate(returns)
        assert result.pairs + result.dropped == len(returns) - 1


def test_variance_ratio_is_about_one_for_a_random_walk():
    rng = np.random.default_rng(6)
    r = rng.normal(0.0, 1.0, 100_000)
    for q in (2, 4, 8):
        assert variance_ratio(r, q) == pytest.approx(1.0, abs=0.05)


def test_variance_ratio_exceeds_one_under_trend_and_falls_below_under_reversal():
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 1.0, 60_000)
    trending = np.empty_like(noise)
    reverting = np.empty_like(noise)
    trending[0] = reverting[0] = noise[0]
    for i in range(1, noise.size):
        trending[i] = noise[i] + 0.3 * trending[i - 1]
        reverting[i] = noise[i] - 0.3 * reverting[i - 1]
    assert variance_ratio(trending, 4) > 1.1
    assert variance_ratio(reverting, 4) < 0.9


def test_variance_ratio_rejects_q_below_two():
    with pytest.raises(ValueError, match="at least 2"):
        variance_ratio(np.zeros(100), 1)


def test_delta_r_squared_recovers_a_planted_linear_link():
    rng = np.random.default_rng(8)
    x = rng.normal(0.0, 1.0, 20_000)
    y = 0.5 * x + rng.normal(0.0, 1.0, 20_000)
    # 信噪比 0.25/1.25 = 0.2
    assert delta_r_squared(x, y) == pytest.approx(0.2, abs=0.02)


def test_excess_kurtosis_is_zero_for_normal_and_large_for_a_fat_tail():
    rng = np.random.default_rng(10)
    assert excess_kurtosis(rng.normal(0.0, 1.0, 200_000)) == pytest.approx(0.0, abs=0.1)
    assert excess_kurtosis(rng.standard_t(df=3, size=200_000)) > 2.0


def test_bootstrap_indices_have_the_right_shape_and_range():
    rng = np.random.default_rng(0)
    idx = stationary_bootstrap_indices(1000, mean_block=24.0, rng=rng)
    assert idx.shape == (1000,)
    assert idx.min() >= 0 and idx.max() < 1000


def test_bootstrap_is_reproducible_from_the_seed():
    a = stationary_bootstrap_indices(500, 12.0, np.random.default_rng(3))
    b = stationary_bootstrap_indices(500, 12.0, np.random.default_rng(3))
    np.testing.assert_array_equal(a, b)


def test_bootstrap_preserves_local_dependence():
    """Blocks must survive resampling, or the null destroys the wrong thing."""
    rng = np.random.default_rng(5)
    n = 20_000
    series = np.cumsum(rng.normal(0.0, 1.0, n))  # 强自相关
    idx = stationary_bootstrap_indices(n, mean_block=200.0, rng=rng)
    resampled = series[idx]
    # 平均块长 200 时,绝大多数相邻位置仍是原序列的相邻位置
    contiguous = float(np.mean(np.diff(idx) == 1))
    assert contiguous > 0.9
    assert np.isfinite(resampled).all()


def test_block_length_is_longer_for_more_persistent_series():
    rng = np.random.default_rng(6)
    iid = rng.normal(0.0, 1.0, 20_000)
    persistent = np.empty(20_000)
    persistent[0] = 0.0
    for i in range(1, 20_000):
        persistent[i] = 0.95 * persistent[i - 1] + rng.normal(0.0, 1.0)
    assert select_block_length(persistent) > select_block_length(iid)


def test_block_length_is_a_multiple_of_twelve_and_at_least_twelve():
    rng = np.random.default_rng(7)
    length = select_block_length(rng.normal(0.0, 1.0, 10_000))
    assert length >= 12
    assert length % 12 == 0


def test_sidak_alpha_matches_three_primary_measures():
    assert pytest.approx(1.0 - 0.95 ** (1.0 / 3.0), abs=1e-6) == SIDAK_ALPHA


def test_combined_p_is_small_when_every_scale_shifts_the_same_way():
    rng = np.random.default_rng(0)
    null_draws = rng.normal(0.0, 1.0, size=(2000, 4))
    observed = np.array([3.0, 3.2, 2.8, 3.1])
    result = combine_scales(observed, null_draws)
    assert result.p_value < 0.001
    assert result.sign_agreement == 4


def test_combined_p_is_large_when_the_shift_is_pure_noise():
    rng = np.random.default_rng(1)
    null_draws = rng.normal(0.0, 1.0, size=(2000, 4))
    observed = np.array([0.1, -0.2, 0.05, -0.1])
    assert combine_scales(observed, null_draws).p_value > 0.2


def test_sign_agreement_counts_the_majority_direction():
    rng = np.random.default_rng(2)
    null_draws = rng.normal(0.0, 1.0, size=(500, 4))
    result = combine_scales(np.array([2.0, 2.0, 2.0, -2.0]), null_draws)
    assert result.sign_agreement == 3


def test_gates_pass_only_when_all_three_hold():
    passing = evaluate_gates(
        combined={"rank_autocorrelation": 0.001, "hit_rate": 0.5, "delta_power": 0.4},
        sign_agreement={"rank_autocorrelation": 4, "hit_rate": 2, "delta_power": 2},
        kurtosis_reduced_scales=4,
        n_scales=4,
    )
    assert passing.g1_passed and passing.g2_passed and passing.g3_passed
    assert passing.verdict == "PASS"
    assert passing.winning_measure == "rank_autocorrelation"


def test_broken_clock_fails_the_kurtosis_gate_even_with_a_significant_result():
    """G2 failing means the clock is broken, so the verdict must not be CLOSED."""
    report = evaluate_gates(
        combined={"rank_autocorrelation": 0.0001, "hit_rate": 0.5, "delta_power": 0.4},
        sign_agreement={"rank_autocorrelation": 4, "hit_rate": 2, "delta_power": 2},
        kurtosis_reduced_scales=1,
        n_scales=4,
    )
    assert not report.g2_passed
    assert report.verdict == "INVALID"


def test_significant_but_inconsistent_signs_is_closed():
    report = evaluate_gates(
        combined={"rank_autocorrelation": 0.0001, "hit_rate": 0.5, "delta_power": 0.4},
        sign_agreement={"rank_autocorrelation": 2, "hit_rate": 2, "delta_power": 2},
        kurtosis_reduced_scales=4,
        n_scales=4,
    )
    assert report.g1_passed and not report.g3_passed
    assert report.verdict == "CLOSED"


def test_nothing_significant_is_closed():
    report = evaluate_gates(
        combined={"rank_autocorrelation": 0.3, "hit_rate": 0.5, "delta_power": 0.4},
        sign_agreement={"rank_autocorrelation": 4, "hit_rate": 4, "delta_power": 4},
        kurtosis_reduced_scales=4,
        n_scales=4,
    )
    assert not report.g1_passed
    assert report.verdict == "CLOSED"


def test_combine_raises_when_observed_contains_nan():
    """Non-finite observed values prevent running the check."""
    rng = np.random.default_rng(11)
    null_draws = rng.normal(0.0, 1.0, size=(500, 3))
    observed = np.array([1.0, np.nan, 2.0])
    with pytest.raises(ValueError, match="non-finite"):
        combine_scales(observed, null_draws)


def test_combine_raises_when_observed_contains_inf():
    """Infinite observed values prevent running the check."""
    rng = np.random.default_rng(12)
    null_draws = rng.normal(0.0, 1.0, size=(500, 3))
    observed = np.array([1.0, np.inf, 2.0])
    with pytest.raises(ValueError, match="non-finite"):
        combine_scales(observed, null_draws)


def test_combine_raises_when_null_variance_is_zero():
    """A scale with zero variance in the null kills the normalization."""
    observed = np.array([1.0, 2.0, 3.0])
    null_draws = np.array(
        [
            [0.0, 1.0, 1.0],
            [0.0, 2.0, 2.0],
            [0.0, 3.0, 3.0],
        ]
    )
    with pytest.raises(ValueError, match="zero or negative variance"):
        combine_scales(observed, null_draws)


def test_sign_agreement_is_zero_for_all_zeros():
    """When all deltas are zero, there is no direction; sign_agreement == 0."""
    rng = np.random.default_rng(13)
    null_draws = rng.normal(0.0, 1.0, size=(500, 4))
    result = combine_scales(np.array([0.0, 0.0, 0.0, 0.0]), null_draws)
    assert result.sign_agreement == 0


def test_sign_agreement_excludes_zeros_from_both_counts():
    """Zeros are not counted as positive or negative; only directional values."""
    rng = np.random.default_rng(14)
    null_draws = rng.normal(0.0, 1.0, size=(500, 4))
    # 2 zeros, 2 negative
    result = combine_scales(np.array([0.0, -1.0, 0.0, -2.0]), null_draws)
    assert result.sign_agreement == 2


def test_sign_agreement_uses_majority_of_non_zero():
    """When more scales are positive than negative, agree is count of positives."""
    rng = np.random.default_rng(15)
    null_draws = rng.normal(0.0, 1.0, size=(500, 4))
    # 2 zeros, 1 negative, 1 positive: positive wins with 1
    result = combine_scales(np.array([0.0, -1.0, 1.0, 0.0]), null_draws)
    assert result.sign_agreement == 1


def test_winning_measure_breaks_p_ties_alphabetically():
    """When two measures share the winning p-value, the earliest alphabetically wins."""
    # Construct two dicts with identical content but different insertion order.
    combined_order_1 = {"hit_rate": 0.01, "rank_autocorrelation": 0.01}
    combined_order_2 = {"rank_autocorrelation": 0.01, "hit_rate": 0.01}
    sign_agreement = {"hit_rate": 4, "rank_autocorrelation": 4}

    report_1 = evaluate_gates(
        combined=combined_order_1,
        sign_agreement=sign_agreement,
        kurtosis_reduced_scales=4,
        n_scales=4,
    )
    report_2 = evaluate_gates(
        combined=combined_order_2,
        sign_agreement=sign_agreement,
        kurtosis_reduced_scales=4,
        n_scales=4,
    )
    assert report_1.winning_measure == "hit_rate"
    assert report_2.winning_measure == "hit_rate"
    assert report_1.winning_measure == report_2.winning_measure


def _synthetic_random_walk(n: int, seed: int):
    """A series with no exploitable structure and realistically skewed turnover."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.004, n)
    # Same length on purpose: this mirrors the aligned pipeline, where the first
    # bar is dropped so that returns[i] is the return of turnover bar i.
    quote_volume = rng.lognormal(mean=11.0, sigma=1.6, size=n)
    return returns, quote_volume


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_p_values_are_uniform_on_data_with_no_effect():
    """The meta-test. A miscalibrated null shows up here and nowhere else."""
    # factor=1 is excluded by design, not by convenience: sample-size matching
    # would ask for as many buckets as bars, every bucket would hold exactly one
    # bar, and the two clocks would partition identically -- Delta identically
    # zero and a null with no variance. The real protocol's ladder starts at 15m.
    factors = [3, 12, 48]
    p_values = []
    for trial in range(40):
        returns, quote_volume = _synthetic_random_walk(12_000, seed=1000 + trial)
        edges = {}
        for factor in factors:
            target_count = len(returns) // factor
            solution = solve_bucket_size(quote_volume, target_count)
            edges[factor] = bucket_edges(quote_volume, solution.target_value)
        observed, draws = paired_null_draws(
            returns_5m=returns,
            quote_volume=quote_volume,
            edges_by_scale=edges,
            calendar_factors=factors,
            measure="rank_autocorrelation",
            draws=200,
            mean_block=24.0,
            seed=trial,
        )
        p_values.append(combine_scales(observed, draws).p_value)

    # 均匀分布的 KS 检验: p 值本身不应显著偏离 U(0,1)
    ks_p = scipy_stats.kstest(p_values, "uniform").pvalue
    assert ks_p > 0.01, f"null is miscalibrated: KS p={ks_p:.4f}"


def test_null_draws_have_the_requested_shape():
    returns, quote_volume = _synthetic_random_walk(3_000, seed=1)
    solution = solve_bucket_size(quote_volume, 3_000)
    edges = {1: bucket_edges(quote_volume, solution.target_value)}
    observed, draws = paired_null_draws(
        returns_5m=returns,
        quote_volume=quote_volume,
        edges_by_scale=edges,
        calendar_factors=[1],
        measure="rank_autocorrelation",
        draws=50,
        mean_block=24.0,
        seed=0,
    )
    assert observed.shape == (1,)
    assert draws.shape == (50, 1)


def test_delta_null_leaves_forward_returns_and_turnover_untouched():
    """spec D3: the delta null reshuffles delta only — nothing else may move."""
    rng = np.random.default_rng(20)
    dollar_delta = {1: rng.normal(0.0, 1.0, 4000)}
    dollar_forward = {1: rng.normal(0.0, 1.0, 4000)}
    calendar_delta = {1: rng.normal(0.0, 1.0, 4000)}
    calendar_forward = {1: rng.normal(0.0, 1.0, 4000)}
    before = dollar_forward[1].copy()
    observed, draws = delta_paired_null_draws(
        dollar_delta=dollar_delta,
        dollar_forward=dollar_forward,
        calendar_delta=calendar_delta,
        calendar_forward=calendar_forward,
        factors=[1],
        draws=30,
        mean_block=24.0,
        seed=0,
    )
    np.testing.assert_array_equal(dollar_forward[1], before)
    assert observed.shape == (1,)
    assert draws.shape == (30, 1)


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_delta_null_p_values_are_uniform_when_delta_carries_nothing():
    """Same meta-test, applied to the second null. An i.i.d. shuffle fails this."""
    p_values = []
    for trial in range(40):
        rng = np.random.default_rng(500 + trial)

        # delta 与 forward 各自有局部依赖, 但彼此无耦合 -> 真零效应
        def ar1(n, phi, gen):
            out = np.empty(n)
            out[0] = gen.normal()
            for i in range(1, n):
                out[i] = phi * out[i - 1] + gen.normal()
            return out

        observed, draws = delta_paired_null_draws(
            dollar_delta={1: ar1(3000, 0.5, rng)},
            dollar_forward={1: ar1(3000, 0.5, rng)},
            calendar_delta={1: ar1(3000, 0.5, rng)},
            calendar_forward={1: ar1(3000, 0.5, rng)},
            factors=[1],
            draws=200,
            mean_block=24.0,
            seed=trial,
        )
        p_values.append(combine_scales(observed, draws).p_value)

    ks_p = scipy_stats.kstest(p_values, "uniform").pvalue
    assert ks_p > 0.01, f"delta null is miscalibrated: KS p={ks_p:.4f}"


def test_null_draws_are_reproducible_from_the_seed():
    returns, quote_volume = _synthetic_random_walk(3_000, seed=2)
    solution = solve_bucket_size(quote_volume, 3_000)
    edges = {1: bucket_edges(quote_volume, solution.target_value)}
    kwargs = dict(
        returns_5m=returns,
        quote_volume=quote_volume,
        edges_by_scale=edges,
        calendar_factors=[1],
        measure="rank_autocorrelation",
        draws=20,
        mean_block=24.0,
        seed=42,
    )
    first = paired_null_draws(**kwargs)
    second = paired_null_draws(**kwargs)
    np.testing.assert_array_equal(first[1], second[1])


def test_aggregate_returns_refuses_a_misaligned_edge():
    """A bucket edge past the end of returns means bars and returns were never
    aligned by the caller -- this must raise, not silently trim, because a
    shifted bucket still looks like a valid number to every downstream check."""
    returns = np.zeros(5)
    with pytest.raises(ValueError, match="misaligned"):
        _aggregate_returns(returns, np.array([2, 6], dtype=np.int64))
