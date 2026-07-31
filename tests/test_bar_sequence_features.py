import numpy as np
import pytest

from cq.research.bar_sequence.features import build_windows, standardize


def test_build_windows_alignment_on_a_known_sequence():
    # returns[k] represents r_{k+1}. With N=2, the first valid decision point
    # is k=1 (needs returns[0], returns[1]); label is returns[2].
    returns = np.array([0.1, -0.2, 0.3, -0.4, 0.5])
    k, sign_w, ret_w, label = build_windows(returns, N=2)

    assert list(k) == [1, 2, 3]  # last valid k is len(returns)-2 = 3
    np.testing.assert_allclose(ret_w[0], [0.1, -0.2])
    np.testing.assert_allclose(ret_w[1], [-0.2, 0.3])
    np.testing.assert_allclose(ret_w[2], [0.3, -0.4])
    np.testing.assert_allclose(label, [0.3, -0.4, 0.5])
    np.testing.assert_allclose(sign_w[0], [1.0, -1.0])


def test_build_windows_accepts_boundary_case_n_equals_m0_minus_1():
    # When N == len(returns) - 1, there is exactly one valid decision point.
    # This is the maximum N that produces at least one window.
    returns = np.array([0.1, -0.2, 0.3, -0.4])  # M0 = 4
    k, sign_w, ret_w, label = build_windows(returns, N=3)  # N = M0 - 1

    assert list(k) == [2]  # k = N - 1 = 2 is the only decision point
    np.testing.assert_allclose(ret_w[0], [0.1, -0.2, 0.3])
    np.testing.assert_allclose(label, [-0.4])  # label = returns[k+1] = returns[3]


def test_build_windows_rejects_n_with_no_valid_decision_points():
    returns = np.array([0.1, -0.2, 0.3])
    with pytest.raises(ValueError):
        build_windows(returns, N=3)  # N must leave room for at least one label


def test_standardize_uses_only_train_rows():
    ret_window = np.array([[1.0, 2.0], [3.0, 4.0], [100.0, 100.0]])
    train_rows = np.array([True, True, False])  # exclude the outlier row
    z = standardize(ret_window, train_rows)

    train_mean = ret_window[train_rows].mean()
    train_std = ret_window[train_rows].std(ddof=1)
    expected = (ret_window - train_mean) / train_std
    np.testing.assert_allclose(z, expected)
