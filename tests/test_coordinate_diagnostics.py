import numpy as np
import pytest

from cq.research.coordinate_diagnostics import (
    delta_r_squared,
    direction_hit_rate,
    excess_kurtosis,
    rank_autocorrelation,
    rank_predictive_power,
    select_block_length,
    stationary_bootstrap_indices,
    variance_ratio,
)


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
