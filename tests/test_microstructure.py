import numpy as np
import pytest

from cq.research.microstructure import centroid_delta, log_returns, vwap


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
