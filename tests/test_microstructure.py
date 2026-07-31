import numpy as np
import pytest

from cq.research.microstructure import (
    centroid_delta,
    corwin_schultz_spread,
    log_returns,
    vwap,
    vwap_position,
)


def test_log_returns_are_additive_across_aggregation():
    close = np.array([1.0, 2.0, 4.0, 8.0])
    r = log_returns(close)
    assert r.shape == (3,)
    np.testing.assert_allclose(r, np.log(2.0), rtol=1e-12)
    # 可加性: 这正是选对数收益而非简单收益的理由
    assert np.isclose(r.sum(), np.log(close[-1] / close[0]))


def test_vwap_is_quote_over_base_and_nan_on_zero_volume():
    qv = np.array([100.0, 0.0])
    v = np.array([50.0, 0.0])
    out = vwap(qv, v)
    assert out[0] == pytest.approx(2.0)
    assert np.isnan(out[1])


def test_centroid_delta_hand_computed():
    # H=10, L=0, C=8, VWAP=200/50=4  ->  delta = (8-4)/(10-0) = 0.4
    d = centroid_delta(
        high=np.array([10.0]),
        low=np.array([0.0]),
        close=np.array([8.0]),
        quote_volume=np.array([200.0]),
        volume=np.array([50.0]),
    )
    assert d[0] == pytest.approx(0.4)


def test_centroid_delta_is_zero_when_bar_is_flat_or_empty():
    d = centroid_delta(
        high=np.array([5.0, 5.0]),
        low=np.array([5.0, 4.0]),
        close=np.array([5.0, 5.0]),
        quote_volume=np.array([100.0, 0.0]),
        volume=np.array([20.0, 0.0]),
    )
    assert d[0] == 0.0  # H == L
    assert d[1] == 0.0  # volume == 0, VWAP 未定义


def test_centroid_delta_stays_in_unit_interval():
    rng = np.random.default_rng(0)
    n = 500
    low = rng.uniform(1.0, 2.0, n)
    high = low + rng.uniform(0.01, 0.5, n)
    close = rng.uniform(low, high)
    volume = rng.uniform(1.0, 100.0, n)
    # VWAP 必须落在 [L, H] 内才是合法的成交均价
    quote_volume = rng.uniform(low, high) * volume
    d = centroid_delta(high, low, close, quote_volume, volume)
    assert np.all(d >= -1.0) and np.all(d <= 1.0)


def test_vwap_position_hand_computed():
    # H=10, L=0, VWAP=200/50=4  ->  v = (4-0)/(10-0) = 0.4
    v = vwap_position(
        high=np.array([10.0]),
        low=np.array([0.0]),
        quote_volume=np.array([200.0]),
        volume=np.array([50.0]),
    )
    assert v[0] == pytest.approx(0.4)


def test_vwap_position_is_nan_when_high_equals_low():
    v = vwap_position(
        high=np.array([5.0]),
        low=np.array([5.0]),
        quote_volume=np.array([100.0]),
        volume=np.array([20.0]),
    )
    assert np.isnan(v[0])


def test_vwap_position_is_nan_on_zero_volume():
    v = vwap_position(
        high=np.array([10.0]),
        low=np.array([0.0]),
        quote_volume=np.array([0.0]),
        volume=np.array([0.0]),
    )
    assert np.isnan(v[0])


def test_vwap_position_stays_in_unit_interval_when_defined():
    rng = np.random.default_rng(0)
    n = 500
    low = rng.uniform(1.0, 2.0, n)
    high = low + rng.uniform(0.01, 0.5, n)
    volume = rng.uniform(1.0, 100.0, n)
    # VWAP must land inside [L, H] to be a legitimate traded average price.
    quote_volume = rng.uniform(low, high) * volume
    v = vwap_position(high, low, quote_volume, volume)
    assert np.all(np.isfinite(v))
    assert np.all(v >= 0.0) and np.all(v <= 1.0)


def test_spread_is_zero_when_price_never_moves():
    # 无波动 -> beta = gamma = 0 -> alpha = 0 -> S = 0
    high = np.full(10, 5.0)
    low = np.full(10, 5.0)
    s = corwin_schultz_spread(high, low)
    assert s.shape == (9,)
    np.testing.assert_allclose(s, 0.0, atol=1e-12)


def test_spread_is_nonnegative_and_finite_on_random_bars():
    rng = np.random.default_rng(7)
    n = 2000
    mid = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.002, n)))
    half = mid * rng.uniform(0.0005, 0.004, n)
    high = mid + half
    low = mid - half
    s = corwin_schultz_spread(high, low)
    assert np.all(np.isfinite(s))
    assert np.all(s >= 0.0)


def test_spread_rises_with_injected_bid_ask_bounce():
    """A wider true spread must produce a wider estimate."""
    rng = np.random.default_rng(11)
    n = 4000
    mid = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.001, n)))
    narrow = corwin_schultz_spread(mid * 1.0005, mid * 0.9995)
    wide = corwin_schultz_spread(mid * 1.005, mid * 0.995)
    assert np.median(wide) > np.median(narrow)


def test_spread_rejects_non_positive_high():
    high = np.array([5.0, 0.0, 5.0])
    low = np.array([4.0, 4.0, 4.0])
    with pytest.raises(ValueError, match="high must be strictly positive"):
        corwin_schultz_spread(high, low)


def test_spread_rejects_non_positive_low():
    high = np.array([5.0, 5.0, 5.0])
    low = np.array([4.0, -1.0, 4.0])
    with pytest.raises(ValueError, match="low must be strictly positive"):
        corwin_schultz_spread(high, low)


def test_spread_rejects_high_below_low():
    high = np.array([5.0, 3.0, 5.0])
    low = np.array([4.0, 4.0, 4.0])
    with pytest.raises(ValueError, match="high must be >= low"):
        corwin_schultz_spread(high, low)


def test_spread_rejects_mismatched_lengths():
    high = np.array([5.0, 5.0, 5.0])
    low = np.array([4.0, 4.0])
    with pytest.raises(ValueError, match="same shape"):
        corwin_schultz_spread(high, low)


def test_spread_does_not_collapse_to_zero_when_exp_alpha_would_overflow():
    """The old `2(e^a - 1) / (1 + e^a)` form overflows exp() to inf for a huge
    alpha, giving nan, which the trailing `isfinite` guard then zeroes out --
    reading the widest possible spread as zero cost, the worst-case direction
    for a cost gate. Two identical bars at the extremes of float64 (high =
    DBL_MAX, low = 1.0) drive alpha to ~709.78, right at exp()'s overflow
    threshold, and used to reproduce exactly that failure.
    """
    dbl_max = np.finfo(np.float64).max
    high = np.array([dbl_max, dbl_max])
    low = np.array([1.0, 1.0])
    s = corwin_schultz_spread(high, low)
    assert s.shape == (1,)
    assert np.isfinite(s[0])
    # 2*tanh(alpha/2) saturates towards its upper bound of 2.0 as alpha -> inf;
    # the old formula would have given exactly 0.0 here.
    assert s[0] == pytest.approx(2.0, abs=1e-6)
