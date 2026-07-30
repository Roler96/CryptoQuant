# tests/test_dollar_clock.py
import numpy as np

from cq.research.dollar_clock import bucket_edges


def test_edges_close_on_first_bar_that_reaches_target():
    qv = np.array([3.0, 3.0, 3.0, 3.0])
    # cumulative 3,6 -> 6>=5 close bucket at index 1; then cumulative 3,6 ->
    # close bucket at index 3
    np.testing.assert_array_equal(bucket_edges(qv, 5.0), np.array([2, 4]))


def test_overflow_does_not_carry_into_the_next_bucket():
    qv = np.array([100.0, 1.0, 1.0, 100.0])
    # first bar exceeds 100 >= 10, overflow 90 is discarded and not carried
    # forward; if carried forward, 1+1 would immediately fill the second bucket
    # -- the assertion verifies it doesn't
    edges = bucket_edges(qv, 10.0)
    np.testing.assert_array_equal(edges, np.array([1, 4]))


def test_trailing_partial_bucket_is_discarded():
    qv = np.array([10.0, 1.0, 1.0])
    np.testing.assert_array_equal(bucket_edges(qv, 10.0), np.array([1]))


def test_zero_volume_bars_are_absorbed_into_the_neighbouring_bucket():
    qv = np.array([4.0, 0.0, 0.0, 6.0])
    # zero-volume bars do not advance accumulation, absorbed into the bucket
    # that spans them
    np.testing.assert_array_equal(bucket_edges(qv, 10.0), np.array([4]))


def test_no_bucket_when_total_is_below_target():
    assert bucket_edges(np.array([1.0, 2.0]), 100.0).size == 0


def test_every_bucket_meets_or_exceeds_the_target():
    rng = np.random.default_rng(3)
    qv = rng.lognormal(mean=10.0, sigma=2.0, size=20_000)
    target = 5.0 * float(np.median(qv))
    edges = bucket_edges(qv, target)
    starts = np.concatenate(([0], edges[:-1]))
    sums = np.array([qv[a:b].sum() for a, b in zip(starts, edges, strict=True)])
    assert np.all(sums >= target)
