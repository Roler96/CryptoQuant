# tests/test_dollar_clock.py
import numpy as np

from cq.research.dollar_clock import bucket_edges, solve_bucket_size


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


def test_solved_size_hits_the_requested_count_within_tolerance():
    rng = np.random.default_rng(5)
    qv = rng.lognormal(mean=9.0, sigma=1.5, size=50_000)
    solution = solve_bucket_size(qv, target_count=5_000)
    assert solution.converged
    assert abs(solution.count - 5_000) <= max(1, int(0.001 * 5_000))


def test_solution_is_deterministic():
    rng = np.random.default_rng(5)
    qv = rng.lognormal(mean=9.0, sigma=1.5, size=20_000)
    first = solve_bucket_size(qv, target_count=2_000)
    second = solve_bucket_size(qv, target_count=2_000)
    assert first == second


def test_naive_target_undershoots_the_count_which_is_why_solving_is_needed():
    """Overshoot means total/N buckets fewer than N -- the bug this task fixes."""
    rng = np.random.default_rng(9)
    qv = rng.lognormal(mean=9.0, sigma=2.5, size=30_000)
    naive_count = len(bucket_edges(qv, float(qv.sum()) / 3_000))
    assert naive_count < 3_000
    assert solve_bucket_size(qv, target_count=3_000).converged


def test_impossible_target_reports_failure_rather_than_looping_forever():
    qv = np.full(100, 1.0)
    # 100 根 bar 无法切出 500 个桶
    solution = solve_bucket_size(qv, target_count=500)
    assert not solution.converged
    assert solution.iterations <= 100


def test_heavy_tailed_turnover_still_converges():
    """The bracket must hold where the tail is fattest -- that is the whole subject.

    A heuristic lower bound (e.g. total/(N*50)) can start *above* the true
    solution here, pinning the search and reporting a reachable target as
    unconverged.
    """
    rng = np.random.default_rng(31)
    qv = rng.lognormal(mean=9.0, sigma=3.4, size=40_000)
    solution = solve_bucket_size(qv, target_count=4_000)
    assert solution.converged
    assert abs(solution.count - 4_000) <= max(1, int(0.001 * 4_000))


def test_unreachable_target_exits_immediately_without_burning_iterations():
    qv = np.full(50, 1.0)
    solution = solve_bucket_size(qv, target_count=500)
    assert not solution.converged
    assert solution.iterations == 0


def test_early_exit_respects_tolerance_boundary():
    """Early exit when reachable < target_count should still apply tolerance rule.

    The early exit occurs when low bound (theoretical maximum bucket count) is
    reached. If the shortfall is within tolerance, the solution is convergent
    even with zero iterations.
    """
    qv = np.full(999, 1.0)
    # tolerance = max(1, int(0.001 * 1000)) = 1
    # reachable = 999, diff = 1, must be converged
    solution = solve_bucket_size(qv, target_count=1000)
    assert solution.converged
    assert solution.count == 999
    assert solution.iterations == 0


def test_bisection_terminates_when_floating_point_precision_exhausted():
    """Bisection exits early when mid can no longer change due to floating point.

    With uniform bar values and a target falling between reachable bucket counts,
    the interval inevitably shrinks until mid == low or mid == high. The early
    termination check `if mid == low or mid == high` prevents pointless
    recomputation of bucket_edges when the bracket is exhausted.
    """
    # Construct data where bucket count is highly quantized: large uniform bars
    # so many bucket sizes give identical bucket counts. Request a target
    # between two reachable counts.
    qv = np.full(120_000, 1.0)
    # low bound gives 120000 buckets, high bound gives 1 bucket.
    # Request 60000 buckets: will likely not be exactly reachable.
    # Bisection must terminate via mid in (low, high), not hit max_iter.
    solution = solve_bucket_size(qv, target_count=60_000)
    assert solution.iterations < 100  # proves early exit fired
