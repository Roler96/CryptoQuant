# tests/test_dollar_clock.py
import numpy as np
import pandas as pd
import pytest

from cq.research.dollar_clock import (
    aggregate_by_edges,
    aggregate_calendar,
    bucket_edges,
    solve_bucket_size,
)


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
    """Prove the collapse break fires, not merely that the loop ended early.

    59_999 is deliberately not exactly reachable for this input: no bucket size
    yields that count. The loop therefore cannot leave through the
    `count == target_count` break, so an early exit can only be the collapse
    branch. Asserting count != target_count is what separates the two paths --
    `iterations < 100` alone cannot.
    """
    qv = np.full(120_000, 1.0)
    solution = solve_bucket_size(qv, target_count=59_999)
    assert solution.iterations < 100
    assert solution.count != 59_999


BAR_MS = 300_000


def _frame(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 0.1 * np.exp(np.cumsum(rng.normal(0.0, 0.003, n)))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0.0, 0.001, n)) * close
    index = pd.to_datetime(np.arange(n) * BAR_MS, unit="ms", utc=True)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread,
            "close": close,
            "volume": rng.lognormal(10.0, 1.0, n),
            "quote_volume": rng.lognormal(11.0, 1.5, n),
        },
        index=index,
    )


def test_aggregate_by_edges_composes_ohlcv_correctly():
    frame = _frame(6)
    out = aggregate_by_edges(frame, np.array([2, 5]))
    assert list(out.index) == [frame.index[0], frame.index[2]]
    assert out["open"].iloc[0] == frame["open"].iloc[0]
    assert out["close"].iloc[0] == frame["close"].iloc[1]
    assert out["high"].iloc[0] == frame["high"].iloc[:2].max()
    assert out["low"].iloc[0] == frame["low"].iloc[:2].min()
    assert out["volume"].iloc[0] == pytest.approx(frame["volume"].iloc[:2].sum())
    assert out["bars"].iloc[0] == 2
    assert out["bars"].iloc[1] == 3


def test_bucket_duration_counts_the_calendar_time_the_bucket_consumed():
    frame = _frame(6)
    out = aggregate_by_edges(frame, np.array([2, 5]))
    # 这是关键的新变量: 等额之后, 信息守恒地转移到桶耗掉的日历时长上
    assert out["duration_ms"].iloc[0] == 2 * BAR_MS
    assert out["duration_ms"].iloc[1] == 3 * BAR_MS


def test_last_bucket_excludes_the_discarded_tail():
    """reduceat's final segment runs to the array end; the tail must not leak in.

    `bucket_edges` drops the trailing partial bucket, so edges[-1] is normally
    short of the frame. A naive reduceat gives the last bucket those dropped
    bars for free — and every other column would still look correct.
    """
    frame = _frame(6)
    out = aggregate_by_edges(frame, np.array([2, 5]))
    assert out["volume"].iloc[-1] == pytest.approx(frame["volume"].iloc[2:5].sum())
    assert out["quote_volume"].iloc[-1] == pytest.approx(frame["quote_volume"].iloc[2:5].sum())
    assert out["high"].iloc[-1] == frame["high"].iloc[2:5].max()
    assert out["low"].iloc[-1] == frame["low"].iloc[2:5].min()
    assert out["close"].iloc[-1] == frame["close"].iloc[4]


def test_aggregate_calendar_matches_edges_at_a_fixed_factor():
    frame = _frame(12)
    by_calendar = aggregate_calendar(frame, factor=3)
    by_edges = aggregate_by_edges(frame, np.array([3, 6, 9, 12]))
    pd.testing.assert_frame_equal(by_calendar, by_edges)


def test_aggregate_calendar_discards_the_trailing_partial_group():
    frame = _frame(11)
    out = aggregate_calendar(frame, factor=3)
    assert len(out) == 3
    assert out["bars"].unique().tolist() == [3]


def test_aggregate_by_edges_on_empty_edges_returns_empty_frame():
    out = aggregate_by_edges(_frame(4), np.array([], dtype=np.int64))
    assert out.empty
    assert list(out.columns) == [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "duration_ms",
        "bars",
    ]


def test_bucket_edges_rejects_non_positive_target():
    with pytest.raises(ValueError, match="target must be positive"):
        bucket_edges(np.array([1.0, 2.0, 3.0]), 0.0)
    with pytest.raises(ValueError, match="target must be positive"):
        bucket_edges(np.array([1.0, 2.0, 3.0]), -5.0)


def test_solve_bucket_size_rejects_non_positive_target_count():
    with pytest.raises(ValueError, match="target_count must be at least 1"):
        solve_bucket_size(np.array([1.0, 2.0, 3.0]), target_count=0)


def test_aggregate_by_edges_rejects_edges_with_non_positive_first_element():
    """`edges[0]` is the right-exclusive end of the first bucket; it must be >= 1."""
    with pytest.raises(ValueError, match=r"edges\[0\] must be >= 1, got 0"):
        aggregate_by_edges(_frame(4), np.array([0, 2]))


def test_aggregate_by_edges_rejects_non_increasing_edges():
    """np.add.reduceat silently returns a[i] instead of summing on a bad index.

    `np.add.reduceat(np.arange(10), [0, 5, 2])` -> `[10, 5, 44]`, no error. A
    non-increasing `edges` array must be rejected up front instead of silently
    producing wrong bars, negative `bars`, and negative `duration_ms`.
    """
    with pytest.raises(ValueError, match=r"edges\[1\]=5 >= edges\[2\]=2"):
        aggregate_by_edges(_frame(10), np.array([2, 5, 2, 8]))


def test_aggregate_by_edges_rejects_repeated_edges():
    with pytest.raises(ValueError, match=r"edges\[0\]=3 >= edges\[1\]=3"):
        aggregate_by_edges(_frame(6), np.array([3, 3, 6]))


def test_aggregate_by_edges_rejects_negative_edges():
    with pytest.raises(ValueError, match=r"edges\[0\] must be >= 1, got -1"):
        aggregate_by_edges(_frame(6), np.array([-1, 3]))
