"""Protocol §7.3: a synthetic series where the correct answer is known by
construction, not eyeballed from real data."""

import numpy as np

from cq.research.bar_sequence.features import build_windows


def test_perfect_lag1_reversal_is_recoverable_from_the_windows():
    # A synthetic series where r_{t+1} = -r_t exactly. If the windowing and
    # alignment contract are correct, sign_window's last column (the most
    # recent return, r_k) must be perfectly anti-correlated with label
    # (r_{k+1}). Any off-by-one in the indexing breaks this trivial relationship.
    rng = np.random.default_rng(0)
    base = rng.normal(size=200)
    returns = np.empty(400)
    returns[0] = base[0]
    for i in range(1, 400):
        returns[i] = -returns[i - 1]

    k, sign_w, ret_w, label = build_windows(returns, N=3)

    last_col_sign = sign_w[:, -1]
    label_sign = np.sign(label)
    assert np.all(last_col_sign == -label_sign)

    last_col_ret = ret_w[:, -1]
    np.testing.assert_allclose(last_col_ret, -label)
