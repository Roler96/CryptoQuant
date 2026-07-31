"""Protocol §7.3: a synthetic series where the correct answer is known by
construction, not eyeballed from real data."""

import numpy as np

from cq.research.bar_sequence.features import build_windows


def test_perfect_lag1_reversal_is_recoverable_from_the_windows():
    # A synthetic series where r_{t+1} = -r_t holds at every even t (pair
    # boundary), built from independently-random per-pair magnitudes -- not
    # a single repeated constant -- so a mis-indexed label (e.g. an
    # off-by-two, not just off-by-one) produces a magnitude mismatch that
    # assert_allclose catches, rather than being silently indistinguishable
    # from correct.
    rng = np.random.default_rng(0)
    base = rng.normal(size=200)
    returns = np.empty(400)
    returns[0::2] = base
    returns[1::2] = -base

    k, sign_w, ret_w, label = build_windows(returns, N=3)

    # The r_{t+1} = -r_t invariant only holds where t is even (pair
    # boundary); between pairs (odd t) it does not, by construction --
    # restrict the assertion to the positions where it provably holds.
    even_mask = (k % 2 == 0)
    assert even_mask.any()

    last_col_sign = sign_w[even_mask, -1]
    label_sign = np.sign(label[even_mask])
    assert np.all(last_col_sign == -label_sign)

    last_col_ret = ret_w[even_mask, -1]
    np.testing.assert_allclose(last_col_ret, -label[even_mask])
