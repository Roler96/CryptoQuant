# DOGE 成交额时钟坐标系诊断（D 阶段）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现并运行 D 阶段坐标系诊断，判定「DOGE 现货 5m 的可预测结构在成交额时钟上是否强于日历时钟」，产出 PASS 或 CLOSED 的裁决。

**Architecture:** 三个纯函数模块（分桶、微观结构、诊断统计）+ 一个 IO runner。纯函数无 IO、可完整单测——D 阶段的全部可信度押在时钟构造正确上。两个 bootstrap null 都冻结成交额序列，因此桶划分在整个重采样循环里不变，只算一次。

**Tech Stack:** Python 3.11+, numpy, pandas, scipy, pytest, ruff, pyright（均已在 `pyproject.toml`）

## Global Constraints

- 数据源仅 `DOGE-USDT` / `5m`。**不得引入**永续、BTC、funding、open interest
- 窗口仅 explore 窗 `ts ∈ [2021-01-01, 2025-06-01)`。**validate 窗不得触碰**，本阶段不调用 `forward_holdout` 也不调用 `record_holdout_access`
- 收益一律 `r_t = log(C_t / C_{t-1})`（对数收益，跨尺度可加）
- `δ = (C − VWAP) / (H − L)`，`VWAP = quote_volume / volume`；`H == L` 时 `δ = 0`
- 方向命中率剔除 `r == 0` 的样本对，并报告剔除比例
- 尺度集合固定 `{5m, 15m, 1h, 4h}`，对应 5m 聚合因子 `{1, 3, 12, 48}`
- 主测度 3 个 → Šidák family α = 0.05 → 单测度阈值 **0.016952**
- Bootstrap `B = 2000`，`seed = 0`，必须可复现
- `V_s` 二分收敛容差 `|M_s − N_s| ≤ max(1, 0.001 · N_s)`，最多 100 次迭代
- `open` 列不得作为特征，仅用于健全性交叉检验
- ruff line-length 100；`select = ["E","F","W","I","UP","B","SIM","RUF","BLE","S"]`
- 所有新模块置于 `cq/research/`，runner 置于 `scripts/`（沿用 `scripts/discover_bic.py` 惯例）
- **命名**：模块叫 `dollar_clock.py` 而非 `clock.py`——`cq/core/clock.py` 与 `tests/test_clock.py` 已存在，重名会造成混淆

---

## File Structure

| 文件 | 职责 |
|---|---|
| `cq/research/microstructure.py`（新建） | 对数收益、VWAP、δ、Corwin–Schultz 有效价差。纯函数，无 IO |
| `cq/research/dollar_clock.py`（新建） | 等额分桶、`V_s` 二分搜索、桶聚合、日历聚合。纯函数，无 IO |
| `cq/research/coordinate_diagnostics.py`（新建） | 非参数/参数测度、平稳 block bootstrap、两个 null、配对差分、闸门评估。纯函数，无 IO |
| `scripts/diagnose_coordinate.py`（新建） | D 阶段 runner：读库、数据契约断言、跑四尺度、写 JSON。唯一有 IO 的文件 |
| `tests/test_microstructure.py`（新建） | Task 1–2 |
| `tests/test_dollar_clock.py`（新建） | Task 3–5 |
| `tests/test_coordinate_diagnostics.py`（新建） | Task 6–10 |
| `tests/test_diagnose_coordinate_runner.py`（新建） | Task 11 |
| `docs/research/doge-5m/DOLLAR_CLOCK_PROTOCOL_2026-07-30.md`（新建） | 预注册，必须先于跑诊断 commit |
| `docs/research/doge-5m/DOLLAR_CLOCK_RESULTS_2026-07-30.md`（新建） | 裁决 |
| `reports/research/doge_dollar_clock_diagnose.json`（新建） | 机器可读结果 |

---

### Task 1: 微观结构基元（收益、VWAP、δ）

**Files:**
- Create: `cq/research/microstructure.py`
- Test: `tests/test_microstructure.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `log_returns(close: np.ndarray) -> np.ndarray` — 长度 `n-1`
  - `vwap(quote_volume: np.ndarray, volume: np.ndarray) -> np.ndarray` — `volume == 0` 处返回 `np.nan`
  - `centroid_delta(high, low, close, quote_volume, volume) -> np.ndarray` — δ，`H == L` 或 `volume == 0` 处返回 `0.0`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_microstructure.py
import numpy as np
import pytest

from cq.research.microstructure import centroid_delta, log_returns, vwap


def test_log_returns_are_additive_across_aggregation():
    close = np.array([1.0, 2.0, 4.0, 8.0])
    r = log_returns(close)
    assert r.shape == (3,)
    np.testing.assert_allclose(r, np.log(2.0), rtol=1e-12)
    # 可加性：这正是选对数收益而非简单收益的理由
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
    assert d[1] == 0.0  # volume == 0，VWAP 未定义


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_microstructure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cq.research.microstructure'`

- [ ] **Step 3: 写最小实现**

```python
# cq/research/microstructure.py
"""Microstructure quantities readable from 5m OHLCV alone.

`close` is the last tick of a bar — an estimate with sample size one. The
volume-weighted centroid of the same bar carries far more of what happened
inside it, and on DOGE spot 5m the two are nearly orthogonal (measured
correlation 0.1415 between their in-bar positions over the explore window).
That orthogonality is the whole reason this module exists.
"""

from __future__ import annotations

import numpy as np


def log_returns(close: np.ndarray) -> np.ndarray:
    """Log returns, additive across aggregation so scales stay comparable."""
    prices = np.asarray(close, dtype=np.float64)
    return np.diff(np.log(prices))


def vwap(quote_volume: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Volume-weighted average price; NaN where the bar traded nothing."""
    qv = np.asarray(quote_volume, dtype=np.float64)
    vol = np.asarray(volume, dtype=np.float64)
    return np.divide(qv, vol, out=np.full_like(qv, np.nan), where=vol > 0)


def centroid_delta(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    quote_volume: np.ndarray,
    volume: np.ndarray,
) -> np.ndarray:
    """(C - VWAP) / (H - L): where the close sits relative to where volume traded.

    Large delta means the bar's late move outran its volume — displacement the
    order flow did not confirm. Zero by definition when the bar has no range or
    no trades, so callers never see a NaN they must special-case.
    """
    hi = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)
    cl = np.asarray(close, dtype=np.float64)
    centre = vwap(quote_volume, volume)
    span = hi - lo
    usable = (span > 0) & np.isfinite(centre)
    out = np.zeros_like(hi)
    np.divide(cl - centre, span, out=out, where=usable)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_microstructure.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/microstructure.py tests/test_microstructure.py
git commit -m "feat(research): microstructure primitives for the dollar-clock diagnosis"
```

---

### Task 2: Corwin–Schultz 有效价差

**Files:**
- Modify: `cq/research/microstructure.py`
- Test: `tests/test_microstructure.py`

**Interfaces:**
- Consumes: Task 1 的模块
- Produces: `corwin_schultz_spread(high: np.ndarray, low: np.ndarray) -> np.ndarray` — 长度 `n-1`，第 `i` 个值由 bar `i` 与 `i+1` 估出；负估计截断为 `0.0`

- [ ] **Step 1: 写失败的测试**

```python
# 追加到 tests/test_microstructure.py
from cq.research.microstructure import corwin_schultz_spread


def test_spread_is_zero_when_price_never_moves():
    # 无波动 → beta = gamma = 0 → alpha = 0 → S = 0
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_microstructure.py -k spread -v`
Expected: FAIL — `ImportError: cannot import name 'corwin_schultz_spread'`

- [ ] **Step 3: 写最小实现**

```python
# 追加到 cq/research/microstructure.py

_CS_K = 3.0 - 2.0 * np.sqrt(2.0)


def corwin_schultz_spread(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Effective spread estimated from two consecutive bars' high-low ranges.

    Corwin & Schultz (2012). The point of estimating it at all is that this
    project's cost wall has always been a constant 15 bps assumption; a spread
    that varies bar to bar turns cost into a state variable, and a strategy can
    then decline to trade when trading is expensive.

    Negative estimates are a known small-sample artefact of the estimator and
    are truncated to zero rather than propagated.
    """
    hi = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)

    single = np.log(hi / lo) ** 2
    beta = single[:-1] + single[1:]
    hi2 = np.maximum(hi[:-1], hi[1:])
    lo2 = np.minimum(lo[:-1], lo[1:])
    gamma = np.log(hi2 / lo2) ** 2

    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / _CS_K - np.sqrt(gamma / _CS_K)
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    return np.where(np.isfinite(spread), np.maximum(spread, 0.0), 0.0)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_microstructure.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/microstructure.py tests/test_microstructure.py
git commit -m "feat(research): Corwin-Schultz effective spread from high-low ranges"
```

---

### Task 3: 等额分桶

**Files:**
- Create: `cq/research/dollar_clock.py`
- Test: `tests/test_dollar_clock.py`

**Interfaces:**
- Consumes: 无
- Produces: `bucket_edges(quote_volume: np.ndarray, target: float) -> np.ndarray` — 每个桶的右开端索引（`int64`）；尾部未达标的残桶不出现在返回值中

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_dollar_clock.py
import numpy as np
import pytest

from cq.research.dollar_clock import bucket_edges


def test_edges_close_on_first_bar_that_reaches_target():
    qv = np.array([3.0, 3.0, 3.0, 3.0])
    # 累计 3,6 -> 6>=5 收桶于索引 1；再累计 3,6 -> 收桶于索引 3
    np.testing.assert_array_equal(bucket_edges(qv, 5.0), np.array([2, 4]))


def test_overflow_does_not_carry_into_the_next_bucket():
    qv = np.array([100.0, 1.0, 1.0, 100.0])
    # 第一根就超额 100 >= 10，溢出的 90 丢弃不结转；
    # 若结转，1+1 就会立刻凑满第二桶 —— 断言的正是它没有
    edges = bucket_edges(qv, 10.0)
    np.testing.assert_array_equal(edges, np.array([1, 4]))


def test_trailing_partial_bucket_is_discarded():
    qv = np.array([10.0, 1.0, 1.0])
    np.testing.assert_array_equal(bucket_edges(qv, 10.0), np.array([1]))


def test_zero_volume_bars_are_absorbed_into_the_neighbouring_bucket():
    qv = np.array([4.0, 0.0, 0.0, 6.0])
    # 零量 bar 不推进累计，被吸收进跨越它们的那个桶
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_dollar_clock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cq.research.dollar_clock'`

- [ ] **Step 3: 写最小实现**

```python
# cq/research/dollar_clock.py
"""Sampling the tape by traded value instead of by the wall clock.

Over the explore window a 5m bar carries anywhere from 2,163 to 131,612,597
USDT of turnover — the p99/p50 ratio alone is 47x. Feeding both into the same
rule as one observation is what a calendar clock does, and an effect that is
stable in event time gets phase-randomised and averaged away by it. Rebucketing
by equal traded value removes that distortion; what it cannot remove is the 5m
sampling floor, so bucket boundaries land only on 5m edges and every bucket
slightly overshoots its target. That overshoot is measured and reported, never
hidden.
"""

from __future__ import annotations

import numpy as np


def bucket_edges(quote_volume: np.ndarray, target: float) -> np.ndarray:
    """Right-exclusive end index of each equal-dollar bucket.

    A bucket closes on the first 5m bar whose cumulative turnover reaches
    `target`; the overshoot is *not* carried forward, so each bucket is the
    shortest run of bars whose turnover is at least `target`. A trailing run
    that never reaches the target is discarded rather than emitted short.
    """
    if target <= 0.0:
        raise ValueError("target must be positive")
    qv = np.asarray(quote_volume, dtype=np.float64)
    edges: list[int] = []
    accumulated = 0.0
    for index in range(qv.size):
        accumulated += qv[index]
        if accumulated >= target:
            edges.append(index + 1)
            accumulated = 0.0
    return np.asarray(edges, dtype=np.int64)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_dollar_clock.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/dollar_clock.py tests/test_dollar_clock.py
git commit -m "feat(research): equal-dollar bucketing with non-carrying overflow"
```

---

### Task 4: `V_s` 二分搜索（样本量匹配）

**Files:**
- Modify: `cq/research/dollar_clock.py`
- Test: `tests/test_dollar_clock.py`

**Interfaces:**
- Consumes: `bucket_edges`
- Produces: `solve_bucket_size(quote_volume, target_count, max_iter=100) -> BucketSolution`，`BucketSolution` 为 frozen dataclass，字段 `target_value: float`、`count: int`、`iterations: int`、`converged: bool`（`converged` 依容差 `|count − target_count| ≤ max(1, 0.001 · target_count)`）

- [ ] **Step 1: 写失败的测试**

```python
# 追加到 tests/test_dollar_clock.py
from cq.research.dollar_clock import solve_bucket_size


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
    """Overshoot means total/N buckets fewer than N — the bug this task fixes."""
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_dollar_clock.py -k solve -v`
Expected: FAIL — `ImportError: cannot import name 'solve_bucket_size'`

- [ ] **Step 3: 写最小实现**

```python
# 追加到 cq/research/dollar_clock.py（import 段补 dataclass）
from dataclasses import dataclass


@dataclass(frozen=True)
class BucketSolution:
    """The bucket size that makes the dollar clock match a calendar sample count."""

    target_value: float
    count: int
    iterations: int
    converged: bool


def solve_bucket_size(
    quote_volume: np.ndarray,
    target_count: int,
    max_iter: int = 100,
) -> BucketSolution:
    """Bisect the bucket size until the dollar clock emits `target_count` buckets.

    Sample-size matching is what makes the paired comparison fair: both clocks
    must span the same window with the same number of observations, so the only
    remaining difference is where the boundaries fall. Taking the naive
    `total / N` undershoots, because every bucket overshoots its target.

    Bucket count is non-increasing in bucket size, which is what makes the
    bisection valid.
    """
    if target_count < 1:
        raise ValueError("target_count must be at least 1")
    qv = np.asarray(quote_volume, dtype=np.float64)
    total = float(qv.sum())
    if total <= 0.0:
        raise ValueError("quote_volume must contain positive turnover")

    tolerance = max(1, int(0.001 * target_count))
    low = total / (target_count * 50.0)
    high = total
    best = (low, len(bucket_edges(qv, low)))
    used = 0

    for used in range(1, max_iter + 1):
        mid = 0.5 * (low + high)
        count = len(bucket_edges(qv, mid))
        if abs(count - target_count) < abs(best[1] - target_count):
            best = (mid, count)
        if count == target_count:
            best = (mid, count)
            break
        if count > target_count:
            low = mid  # too many buckets: they are too small
        else:
            high = mid

    return BucketSolution(
        target_value=best[0],
        count=best[1],
        iterations=used,
        converged=abs(best[1] - target_count) <= tolerance,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_dollar_clock.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/dollar_clock.py tests/test_dollar_clock.py
git commit -m "feat(research): bisect bucket size to match calendar sample count"
```

---

### Task 5: 桶聚合与日历聚合

**Files:**
- Modify: `cq/research/dollar_clock.py`
- Test: `tests/test_dollar_clock.py`

**Interfaces:**
- Consumes: `bucket_edges`
- Produces:
  - `aggregate_by_edges(frame: pd.DataFrame, edges: np.ndarray) -> pd.DataFrame` — 列 `open, high, low, close, volume, quote_volume, duration_ms, bars`，索引为每桶首根 bar 的 `ts`
  - `aggregate_calendar(frame: pd.DataFrame, factor: int) -> pd.DataFrame` — 同样的列；`factor` 为每组 5m 根数；尾部不足一组的残余丢弃

`frame` 约定：`store.load_ohlcv` 的输出——`DatetimeIndex`（UTC，升序）+ 列 `open, high, low, close, volume, quote_volume`。

- [ ] **Step 1: 写失败的测试**

```python
# 追加到 tests/test_dollar_clock.py
import pandas as pd

from cq.research.dollar_clock import aggregate_by_edges, aggregate_calendar

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
    # 这是关键的新变量：等额之后，信息守恒地转移到桶耗掉的日历时长上
    assert out["duration_ms"].iloc[0] == 2 * BAR_MS
    assert out["duration_ms"].iloc[1] == 3 * BAR_MS


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
        "open", "high", "low", "close", "volume", "quote_volume", "duration_ms", "bars",
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_dollar_clock.py -k aggregate -v`
Expected: FAIL — `ImportError: cannot import name 'aggregate_by_edges'`

- [ ] **Step 3: 写最小实现**

```python
# 追加到 cq/research/dollar_clock.py（import 段补 pandas）
import pandas as pd

BAR_MS = 300_000

_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "duration_ms",
    "bars",
]


def aggregate_by_edges(frame: pd.DataFrame, edges: np.ndarray) -> pd.DataFrame:
    """Collapse 5m bars into the buckets delimited by `edges`.

    `duration_ms` is the calendar time the bucket consumed. Once turnover per
    bucket is held constant, that duration is where the information about
    activity went — and it is a variable no prior study in this repository has
    carried.
    """
    ends = np.asarray(edges, dtype=np.int64)
    if ends.size == 0:
        return pd.DataFrame(columns=_COLUMNS, index=frame.index[:0])

    starts = np.concatenate(([0], ends[:-1]))
    rows = {
        "open": frame["open"].to_numpy()[starts],
        "high": np.maximum.reduceat(frame["high"].to_numpy(), starts),
        "low": np.minimum.reduceat(frame["low"].to_numpy(), starts),
        "close": frame["close"].to_numpy()[ends - 1],
        "volume": np.add.reduceat(frame["volume"].to_numpy(), starts),
        "quote_volume": np.add.reduceat(frame["quote_volume"].to_numpy(), starts),
        "duration_ms": (ends - starts) * BAR_MS,
        "bars": ends - starts,
    }
    return pd.DataFrame(rows, index=frame.index[starts])


def aggregate_calendar(frame: pd.DataFrame, factor: int) -> pd.DataFrame:
    """Collapse 5m bars into fixed groups of `factor` — the calendar clock arm.

    Deliberately routed through the same aggregation as the dollar clock so the
    two arms of the paired comparison cannot differ by an accident of plumbing.
    """
    if factor < 1:
        raise ValueError("factor must be at least 1")
    usable = (len(frame) // factor) * factor
    edges = np.arange(factor, usable + 1, factor, dtype=np.int64)
    return aggregate_by_edges(frame.iloc[:usable], edges)
```

> 注：`np.maximum.reduceat` 依赖 `starts` 严格递增，`bucket_edges` 保证每桶至少含一根 bar，故成立。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_dollar_clock.py -v`
Expected: 15 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/dollar_clock.py tests/test_dollar_clock.py
git commit -m "feat(research): bucket and calendar aggregation sharing one code path"
```

---

### Task 6: 非参数测度（主判据）

**Files:**
- Create: `cq/research/coordinate_diagnostics.py`
- Test: `tests/test_coordinate_diagnostics.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `rank_autocorrelation(returns: np.ndarray, lag: int = 1) -> float`
  - `direction_hit_rate(returns: np.ndarray) -> HitRate`，`HitRate` 为 frozen dataclass，字段 `rate: float`、`pairs: int`、`dropped: int`
  - `rank_predictive_power(feature: np.ndarray, forward_returns: np.ndarray) -> float` — 长度必须相等，调用方负责对齐

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_coordinate_diagnostics.py
import numpy as np
import pytest

from cq.research.coordinate_diagnostics import (
    direction_hit_rate,
    rank_autocorrelation,
    rank_predictive_power,
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
    # 样本对 (t, t+1)：(1,1) 同号、(1,0) 丢、(0,1) 丢、(1,-1) 异号
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cq.research.coordinate_diagnostics'`

- [ ] **Step 3: 写最小实现**

```python
# cq/research/coordinate_diagnostics.py
"""Measuring whether a clock change buys predictability.

The main criteria here are rank-based on purpose. DOGE's right tail is wide
enough that second-moment statistics get dominated by a handful of bars, and
that is the technical root of this project's power wall: the effect was never
required to be absent, only the measurement was required to be blind to it.
Parametric measures are still computed, as corroboration — where the two
disagree, the disagreement is the finding.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class HitRate:
    """Directional agreement between consecutive returns."""

    rate: float
    pairs: int
    dropped: int


def rank_autocorrelation(returns: np.ndarray, lag: int = 1) -> float:
    """Spearman correlation between a return and the return `lag` steps later."""
    if lag < 1:
        raise ValueError("lag must be at least 1")
    values = np.asarray(returns, dtype=np.float64)
    if values.size <= lag + 1:
        return float("nan")
    rho, _ = stats.spearmanr(values[:-lag], values[lag:])
    return float(rho)


def direction_hit_rate(returns: np.ndarray) -> HitRate:
    """How often the next return keeps the current one's sign.

    Flat bars carry no direction, so pairs touching a zero return are dropped
    rather than silently counted as agreement or disagreement.
    """
    signs = np.sign(np.asarray(returns, dtype=np.float64))
    current, following = signs[:-1], signs[1:]
    usable = (current != 0) & (following != 0)
    pairs = int(usable.sum())
    dropped = int(usable.size - pairs)
    if pairs == 0:
        return HitRate(rate=float("nan"), pairs=0, dropped=dropped)
    hits = float((current[usable] == following[usable]).sum())
    return HitRate(rate=hits / pairs, pairs=pairs, dropped=dropped)


def rank_predictive_power(feature: np.ndarray, forward_returns: np.ndarray) -> float:
    """Spearman correlation between a feature and the return that follows it."""
    x = np.asarray(feature, dtype=np.float64)
    y = np.asarray(forward_returns, dtype=np.float64)
    if x.size != y.size:
        raise ValueError("feature and forward_returns must have the same length")
    if x.size < 3:
        return float("nan")
    rho, _ = stats.spearmanr(x, y)
    return float(rho)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/coordinate_diagnostics.py tests/test_coordinate_diagnostics.py
git commit -m "feat(research): rank-based predictability measures for the paired diagnosis"
```

---

### Task 7: 参数测度（佐证 + 健全性）

**Files:**
- Modify: `cq/research/coordinate_diagnostics.py`
- Test: `tests/test_coordinate_diagnostics.py`

**Interfaces:**
- Consumes: Task 6 的模块
- Produces:
  - `variance_ratio(returns: np.ndarray, q: int) -> float` — 随机游走下约等于 1
  - `delta_r_squared(feature: np.ndarray, forward_returns: np.ndarray) -> float` — 单变量 OLS 的 R²
  - `excess_kurtosis(returns: np.ndarray) -> float` — 正态为 0

- [ ] **Step 1: 写失败的测试**

```python
# 追加到 tests/test_coordinate_diagnostics.py
from cq.research.coordinate_diagnostics import (
    delta_r_squared,
    excess_kurtosis,
    variance_ratio,
)


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -k "variance_ratio or r_squared or kurtosis" -v`
Expected: FAIL — `ImportError: cannot import name 'variance_ratio'`

- [ ] **Step 3: 写最小实现**

```python
# 追加到 cq/research/coordinate_diagnostics.py


def variance_ratio(returns: np.ndarray, q: int) -> float:
    """Lo-MacKinlay variance ratio; 1 under a random walk.

    Above 1 is trending, below 1 is reverting. Reported as corroboration only:
    it is a second-moment statistic and therefore exposed to the fat tail the
    rank measures are designed to survive.
    """
    if q < 2:
        raise ValueError("q must be at least 2")
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 2 * q:
        return float("nan")
    single = float(np.var(r, ddof=1))
    if single == 0.0:
        return float("nan")
    aggregated = np.convolve(r, np.ones(q), mode="valid")
    return float(np.var(aggregated, ddof=1) / (q * single))


def delta_r_squared(feature: np.ndarray, forward_returns: np.ndarray) -> float:
    """R-squared of the univariate regression of forward return on the feature."""
    x = np.asarray(feature, dtype=np.float64)
    y = np.asarray(forward_returns, dtype=np.float64)
    if x.size != y.size:
        raise ValueError("feature and forward_returns must have the same length")
    usable = np.isfinite(x) & np.isfinite(y)
    if usable.sum() < 3:
        return float("nan")
    correlation = np.corrcoef(x[usable], y[usable])[0, 1]
    if not np.isfinite(correlation):
        return float("nan")
    return float(correlation**2)


def excess_kurtosis(returns: np.ndarray) -> float:
    """Excess kurtosis; zero for a normal.

    This is the sanity check, not a finding. Aggregating by traded value is
    known to pull return distributions toward normality, so a dollar clock that
    fails to reduce kurtosis indicates a broken clock, not an absent effect.
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 4:
        return float("nan")
    return float(stats.kurtosis(r, fisher=True, bias=False))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -v`
Expected: 12 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/coordinate_diagnostics.py tests/test_coordinate_diagnostics.py
git commit -m "feat(research): parametric corroboration measures and the kurtosis sanity check"
```

---

### Task 8: 平稳 block bootstrap 与两个 null

**Files:**
- Modify: `cq/research/coordinate_diagnostics.py`
- Test: `tests/test_coordinate_diagnostics.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `stationary_bootstrap_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray` — 长度 `n` 的索引数组，环绕取样
  - `select_block_length(returns: np.ndarray, max_lag: int = 288) -> int` — |ACF| 首次落入 ±2/√n 带的 lag，向上取整到 12 的倍数，下限 12

- [ ] **Step 1: 写失败的测试**

```python
# 追加到 tests/test_coordinate_diagnostics.py
from cq.research.coordinate_diagnostics import (
    select_block_length,
    stationary_bootstrap_indices,
)


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
    # 平均块长 200 时，绝大多数相邻位置仍是原序列的相邻位置
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -k "bootstrap or block_length" -v`
Expected: FAIL — `ImportError: cannot import name 'stationary_bootstrap_indices'`

- [ ] **Step 3: 写最小实现**

```python
# 追加到 cq/research/coordinate_diagnostics.py


def stationary_bootstrap_indices(
    n: int,
    mean_block: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Politis-Romano stationary bootstrap: geometric blocks, wrapping at the end.

    Blocks are what keep the null honest. Resampling observation by observation
    would destroy the series' own short-range dependence along with the coupling
    under test, and the resulting null would be far too easy to beat.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    if mean_block <= 0.0:
        raise ValueError("mean_block must be positive")

    restart_probability = 1.0 / mean_block
    indices = np.empty(n, dtype=np.int64)
    current = int(rng.integers(n))
    restarts = rng.random(n) < restart_probability
    for position in range(n):
        if position > 0:
            current = int(rng.integers(n)) if restarts[position] else (current + 1) % n
        indices[position] = current
    return indices


def select_block_length(returns: np.ndarray, max_lag: int = 288) -> int:
    """First lag whose |ACF| falls inside the +-2/sqrt(n) band, rounded up to an hour.

    Pre-registered as a rule rather than a number so it cannot be retuned after
    seeing the result. The 12-bar rounding is one hour of 5m bars.
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 100:
        return 12
    centred = r - r.mean()
    denominator = float(np.dot(centred, centred))
    if denominator == 0.0:
        return 12
    band = 2.0 / np.sqrt(n)
    chosen = max_lag
    for lag in range(1, min(max_lag, n - 1) + 1):
        acf = float(np.dot(centred[:-lag], centred[lag:]) / denominator)
        if abs(acf) < band:
            chosen = lag
            break
    return max(12, int(np.ceil(chosen / 12.0)) * 12)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -v`
Expected: 17 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/coordinate_diagnostics.py tests/test_coordinate_diagnostics.py
git commit -m "feat(research): stationary bootstrap with a pre-registered block length rule"
```

---

### Task 9: 配对差分、合并统计量与闸门

**Files:**
- Modify: `cq/research/coordinate_diagnostics.py`
- Test: `tests/test_coordinate_diagnostics.py`

**Interfaces:**
- Consumes: Task 6–8
- Produces:
  - `combine_scales(observed: np.ndarray, null_draws: np.ndarray) -> Combined` — `observed` 形状 `(n_scales,)`，`null_draws` 形状 `(B, n_scales)`；`Combined` 为 frozen dataclass，字段 `statistic: float`、`p_value: float`、`sign_agreement: int`
  - `SIDAK_ALPHA: float = 0.016952`
  - `evaluate_gates(...) -> GateReport`（签名见实现）

合并统计量 = 各尺度用其 null 的标准差归一化后求和 `T = Σ_s Δ_s / sd_null(Δ_s)`，其 null 分布取自同一批 bootstrap 抽样。这是 spec §D3「在 bootstrap 内直接算合并统计量的 null 分布」的具体实现——比合并 p 值更干净，且跨尺度相关性自动被联合抽样吸收。

- [ ] **Step 1: 写失败的测试**

```python
# 追加到 tests/test_coordinate_diagnostics.py
from cq.research.coordinate_diagnostics import (
    SIDAK_ALPHA,
    combine_scales,
    evaluate_gates,
)


def test_sidak_alpha_matches_three_primary_measures():
    assert SIDAK_ALPHA == pytest.approx(1.0 - 0.95 ** (1.0 / 3.0), abs=1e-6)


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -k "combine or gates or sidak" -v`
Expected: FAIL — `ImportError: cannot import name 'SIDAK_ALPHA'`

- [ ] **Step 3: 写最小实现**

```python
# 追加到 cq/research/coordinate_diagnostics.py

# Three primary measures, family alpha 0.05.
SIDAK_ALPHA = 1.0 - 0.95 ** (1.0 / 3.0)


@dataclass(frozen=True)
class Combined:
    """One measure's evidence, pooled across scales."""

    statistic: float
    p_value: float
    sign_agreement: int


@dataclass(frozen=True)
class GateReport:
    """The pre-registered verdict."""

    g1_passed: bool
    g2_passed: bool
    g3_passed: bool
    winning_measure: str | None
    verdict: str  # PASS | CLOSED | INVALID


def combine_scales(observed: np.ndarray, null_draws: np.ndarray) -> Combined:
    """Pool paired differences across scales against a jointly generated null.

    Each scale is normalised by its own null spread, then summed. Because the
    null draws are generated jointly, the correlation between scales is already
    inside the null distribution of the sum — no independence assumption is made
    anywhere.
    """
    delta = np.asarray(observed, dtype=np.float64)
    draws = np.asarray(null_draws, dtype=np.float64)
    if draws.ndim != 2 or draws.shape[1] != delta.size:
        raise ValueError("null_draws must have shape (B, n_scales)")

    spread = draws.std(axis=0, ddof=1)
    spread = np.where(spread > 0, spread, np.nan)
    statistic = float(np.nansum(delta / spread))
    null_statistics = np.nansum(draws / spread, axis=1)

    # Two-sided, with the +1 that keeps an empirical p-value from ever being 0.
    extreme = int(np.sum(np.abs(null_statistics) >= abs(statistic)))
    p_value = (extreme + 1) / (draws.shape[0] + 1)

    positive = int(np.sum(delta > 0))
    return Combined(
        statistic=statistic,
        p_value=float(p_value),
        sign_agreement=max(positive, delta.size - positive),
    )


def evaluate_gates(
    combined: dict[str, float],
    sign_agreement: dict[str, int],
    kurtosis_reduced_scales: int,
    n_scales: int,
) -> GateReport:
    """Apply G1/G2/G3 exactly as pre-registered in the protocol.

    G2 is deliberately not a research verdict. Aggregating by traded value is
    known to reduce kurtosis; if it did not, the clock is mis-built and the run
    says INVALID rather than pretending to have measured the market.
    """
    required = int(np.ceil(0.75 * n_scales))

    g2_passed = kurtosis_reduced_scales >= required

    significant = {name: p for name, p in combined.items() if p <= SIDAK_ALPHA}
    g1_passed = bool(significant)

    winner = min(significant, key=lambda name: combined[name]) if significant else None
    g3_passed = bool(winner is not None and sign_agreement[winner] >= required)

    if not g2_passed:
        verdict = "INVALID"
    elif g1_passed and g3_passed:
        verdict = "PASS"
    else:
        verdict = "CLOSED"

    return GateReport(
        g1_passed=g1_passed,
        g2_passed=g2_passed,
        g3_passed=g3_passed,
        winning_measure=winner,
        verdict=verdict,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -v`
Expected: 25 passed

- [ ] **Step 5: 提交**

```bash
git add cq/research/coordinate_diagnostics.py tests/test_coordinate_diagnostics.py
git commit -m "feat(research): paired pooling across scales and the pre-registered gates"
```

---

### Task 10: ★ null 元测试（p 值均匀性）

没有这一步，D 阶段的全部显著性都是空的。它在**已知无效应**的数据上跑完整流水线，检查 p 值是否均匀分布——这是唯一能抓出 null 构造错误的手段。

**Files:**
- Modify: `cq/research/coordinate_diagnostics.py`
- Test: `tests/test_coordinate_diagnostics.py`

**Interfaces:**
- Consumes: Task 3–9
- Produces:
  - `paired_null_draws(returns_5m, quote_volume, edges_by_scale, calendar_factors, measure, draws, mean_block, seed) -> tuple[np.ndarray, np.ndarray]` — 返回 `(observed_deltas, null_draws)`，形状 `(n_scales,)` 与 `(draws, n_scales)`
  - `delta_paired_null_draws(dollar_delta, dollar_forward, calendar_delta, calendar_forward, factors, draws, mean_block, seed) -> tuple[np.ndarray, np.ndarray]` — 同样的返回形状。四个 dict 均以 `factor` 为键

**关键实现事实**：两个 null 都冻结成交额序列，所以桶划分在整个循环里不变——`edges_by_scale` 只算一次并传入。这既是性能（2000 次重采样只重算测度），也是 null 设计正确的体现。

**δ null 必须是 block bootstrap 重排 δ，而非置换整个 frame。** spec §D3 要求「重排 δ 序列，收益与成交额都不动」。置换整个 frame 会同时打乱 `close`（收益动了）与 `quote_volume`（成交额动了、桶划分与数据错配），且 i.i.d. 置换破坏局部依赖会让 null 分布过窄——那是**假阳性**的直接来源。因此 δ 与 forward return 在聚合后配好对，null 只对聚合后的 δ 数组做 block 重排。

- [ ] **Step 1: 写失败的测试**

```python
# 追加到 tests/test_coordinate_diagnostics.py
from scipy import stats as scipy_stats

from cq.research.coordinate_diagnostics import delta_paired_null_draws, paired_null_draws
from cq.research.dollar_clock import bucket_edges, solve_bucket_size


def _synthetic_random_walk(n: int, seed: int):
    """A series with no exploitable structure and realistically skewed turnover."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.004, n)
    quote_volume = rng.lognormal(mean=11.0, sigma=1.6, size=n + 1)
    return returns, quote_volume


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_p_values_are_uniform_on_data_with_no_effect():
    """The meta-test. A miscalibrated null shows up here and nowhere else."""
    factors = [1, 3, 12]
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

    # 均匀分布的 KS 检验：p 值本身不应显著偏离 U(0,1)
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
        # delta 与 forward 各自有局部依赖，但彼此无耦合 -> 真零效应
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -k paired_null -v`
Expected: FAIL — `ImportError: cannot import name 'paired_null_draws'`

- [ ] **Step 3: 写最小实现**

```python
# 追加到 cq/research/coordinate_diagnostics.py


def _aggregate_returns(returns: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Sum 5m log returns inside each bucket. Additivity is why they are logs."""
    if ends.size == 0:
        return np.empty(0, dtype=np.float64)
    starts = np.concatenate(([0], ends[:-1]))
    return np.add.reduceat(returns, starts)


def _measure(name: str, aggregated: np.ndarray) -> float:
    if name == "rank_autocorrelation":
        return rank_autocorrelation(aggregated, lag=1)
    if name == "hit_rate":
        return direction_hit_rate(aggregated).rate
    raise ValueError(f"unknown measure {name!r}")


def paired_null_draws(
    returns_5m: np.ndarray,
    quote_volume: np.ndarray,
    edges_by_scale: dict[int, np.ndarray],
    calendar_factors: list[int],
    measure: str,
    draws: int,
    mean_block: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Observed paired differences and their null distribution.

    The null resamples the 5m return series in stationary blocks while leaving
    turnover untouched. Both clocks therefore keep exactly the partition they
    had; the only thing broken is the coupling between when returns happened and
    how much traded. That is precisely the hypothesis "the clock change bought
    nothing", and nothing else about the data is disturbed.

    Because turnover is frozen, `edges_by_scale` is computed once by the caller
    and reused across every draw.
    """
    returns = np.asarray(returns_5m, dtype=np.float64)
    n = returns.size
    rng = np.random.default_rng(seed)

    def deltas(series: np.ndarray) -> np.ndarray:
        out = []
        for factor in calendar_factors:
            usable = (n // factor) * factor
            calendar_ends = np.arange(factor, usable + 1, factor, dtype=np.int64)
            dollar = _measure(measure, _aggregate_returns(series, edges_by_scale[factor]))
            calendar = _measure(measure, _aggregate_returns(series[:usable], calendar_ends))
            out.append(dollar - calendar)
        return np.asarray(out, dtype=np.float64)

    observed = deltas(returns)
    null = np.empty((draws, len(calendar_factors)), dtype=np.float64)
    for draw in range(draws):
        indices = stationary_bootstrap_indices(n, mean_block, rng)
        null[draw] = deltas(returns[indices])
    return observed, null


def delta_paired_null_draws(
    dollar_delta: dict[int, np.ndarray],
    dollar_forward: dict[int, np.ndarray],
    calendar_delta: dict[int, np.ndarray],
    calendar_forward: dict[int, np.ndarray],
    factors: list[int],
    draws: int,
    mean_block: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Observed and null paired differences for delta's predictive power.

    The second null of the protocol: only the delta series is reshuffled, in
    stationary blocks. Returns and turnover are left exactly as they were, so
    both clocks keep their partitions and their price paths — the single thing
    broken is the coupling between the volume centroid and what happens next.

    Shuffling the whole bar instead would move `close` (returns change) and
    `quote_volume` (the buckets no longer match the data), and an i.i.d. shuffle
    would strip the local dependence the block bootstrap exists to preserve —
    narrowing the null and manufacturing significance.
    """
    rng = np.random.default_rng(seed)

    def paired(shuffled: bool) -> np.ndarray:
        out = []
        for factor in factors:
            values = []
            for feature, forward in (
                (dollar_delta[factor], dollar_forward[factor]),
                (calendar_delta[factor], calendar_forward[factor]),
            ):
                series = feature
                if shuffled:
                    series = feature[
                        stationary_bootstrap_indices(feature.size, mean_block, rng)
                    ]
                values.append(abs(rank_predictive_power(series, forward)))
            out.append(values[0] - values[1])
        return np.asarray(out, dtype=np.float64)

    observed = paired(shuffled=False)
    null = np.empty((draws, len(factors)), dtype=np.float64)
    for draw in range(draws):
        null[draw] = paired(shuffled=True)
    return observed, null
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_coordinate_diagnostics.py -v`
Expected: 30 passed（其中 2 个标记 `slow`，耗时数分钟）

若 KS 检验失败，**不要放宽阈值**——那是 null 构造有 bug 的信号。按 `superpowers:systematic-debugging` 排查。

- [ ] **Step 5: 提交**

```bash
git add cq/research/coordinate_diagnostics.py tests/test_coordinate_diagnostics.py
git commit -m "test(research): meta-test proving the paired null is calibrated"
```

---

### Task 11: D 阶段 runner

**Files:**
- Create: `scripts/diagnose_coordinate.py`
- Test: `tests/test_diagnose_coordinate_runner.py`

**Interfaces:**
- Consumes: Task 1–10 全部
- Produces:
  - `assert_contiguous(frame: pd.DataFrame) -> None` — 根数不等于 天数×288 时抛 `ProtocolError`
  - `fingerprint(frame: pd.DataFrame) -> str` — 全表 SHA256 前 16 hex
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_diagnose_coordinate_runner.py
import numpy as np
import pandas as pd
import pytest

from cq.research.split import ProtocolError
from scripts.diagnose_coordinate import assert_contiguous, fingerprint

BAR_MS = 300_000


def _contiguous_frame(days: int) -> pd.DataFrame:
    n = days * 288
    index = pd.to_datetime(np.arange(n) * BAR_MS, unit="ms", utc=True)
    return pd.DataFrame(
        {
            "open": np.ones(n),
            "high": np.ones(n),
            "low": np.ones(n),
            "close": np.ones(n),
            "volume": np.ones(n),
            "quote_volume": np.ones(n),
        },
        index=index,
    )


def test_contiguous_frame_is_accepted():
    assert_contiguous(_contiguous_frame(3))


def test_missing_bar_is_refused_rather_than_interpolated():
    frame = _contiguous_frame(3).drop(index=_contiguous_frame(3).index[100])
    with pytest.raises(ProtocolError, match="contiguous"):
        assert_contiguous(frame)


def test_fingerprint_is_stable_and_sensitive():
    frame = _contiguous_frame(1)
    assert fingerprint(frame) == fingerprint(frame.copy())
    altered = frame.copy()
    altered.iloc[0, altered.columns.get_loc("close")] = 2.0
    assert fingerprint(altered) != fingerprint(frame)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_diagnose_coordinate_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.diagnose_coordinate'`

- [ ] **Step 3: 写最小实现**

先建包标记，否则 `from scripts...` 导入不到：

```bash
touch scripts/__init__.py
```

```python
# scripts/diagnose_coordinate.py
"""D-phase runner: does a dollar clock buy predictability a calendar clock lacks?

Produces a verdict, not a strategy. Nothing here computes a return, a position,
or a cost — the point is to find out whether the coordinate change is worth
building on before any of that exists. A CLOSED verdict is a publishable result:
it says DOGE spot 5m lacks structure in two orthogonal coordinate systems, which
is new evidence rather than a sixteenth variant of an old trigger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.coordinate_diagnostics import (
    SIDAK_ALPHA,
    combine_scales,
    delta_paired_null_draws,
    direction_hit_rate,
    evaluate_gates,
    excess_kurtosis,
    paired_null_draws,
    rank_autocorrelation,
    rank_predictive_power,
    select_block_length,
    variance_ratio,
)
from cq.research.dollar_clock import (
    BAR_MS,
    aggregate_by_edges,
    aggregate_calendar,
    bucket_edges,
    solve_bucket_size,
)
from cq.research.microstructure import centroid_delta, corwin_schultz_spread, log_returns
from cq.research.split import ProtocolError, to_ms

INST_ID = "DOGE-USDT"
TIMEFRAME = "5m"
EXPLORE_START = "2021-01-01"
EXPLORE_END = "2025-06-01"
SCALES = {"5m": 1, "15m": 3, "1h": 12, "4h": 48}
PRIMARY_MEASURES = ("rank_autocorrelation", "hit_rate", "delta_power")
DRAWS = 2000
SEED = 0
DEFAULT_OUT = Path("reports/research/doge_dollar_clock_diagnose.json")


def assert_contiguous(frame: pd.DataFrame) -> None:
    """Refuse a gapped series instead of quietly diagnosing a different one."""
    if frame.empty:
        raise ProtocolError("no bars loaded")
    stamps = frame.index.astype("int64") // 1_000_000
    gaps = np.diff(stamps)
    if not np.all(gaps == BAR_MS):
        bad = int(np.sum(gaps != BAR_MS))
        raise ProtocolError(f"series is not contiguous: {bad} gap(s) at 5m spacing")
    span_days = (stamps[-1] + BAR_MS - stamps[0]) / (86_400_000)
    expected = int(round(span_days * 288))
    if len(frame) != expected:
        raise ProtocolError(f"expected {expected} contiguous bars, loaded {len(frame)}")


def fingerprint(frame: pd.DataFrame) -> str:
    """Content hash so a later run cannot silently diagnose different data."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(frame.index.astype("int64").to_numpy()).tobytes())
    for column in ("open", "high", "low", "close", "volume", "quote_volume"):
        digest.update(np.ascontiguousarray(frame[column].to_numpy(np.float64)).tobytes())
    return digest.hexdigest()[:16]


def _delta_and_forward(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Aligned (delta_t, r_{t+1}) for aggregated bars, dropping the last bar."""
    delta = centroid_delta(
        bars["high"].to_numpy(),
        bars["low"].to_numpy(),
        bars["close"].to_numpy(),
        bars["quote_volume"].to_numpy(),
        bars["volume"].to_numpy(),
    )
    forward = log_returns(bars["close"].to_numpy())
    return delta[:-1], forward


def run(db_path: str, out_path: Path) -> dict:
    with Store(db_path) as store:
        frame = store.load_ohlcv(
            INST_ID, TIMEFRAME, to_ms(EXPLORE_START), to_ms(EXPLORE_END)
        )
    assert_contiguous(frame)

    close = frame["close"].to_numpy(np.float64)
    quote_volume = frame["quote_volume"].to_numpy(np.float64)
    returns = log_returns(close)
    block = select_block_length(returns)

    edges_by_scale: dict[int, np.ndarray] = {}
    fidelity = {}
    for label, factor in SCALES.items():
        target_count = len(frame) // factor
        solution = solve_bucket_size(quote_volume, target_count)
        edges = bucket_edges(quote_volume, solution.target_value)
        edges_by_scale[factor] = edges
        starts = np.concatenate(([0], edges[:-1])) if edges.size else np.empty(0, np.int64)
        sums = np.add.reduceat(quote_volume, starts) if edges.size else np.empty(0)
        fidelity[label] = {
            "target_value": solution.target_value,
            "buckets": int(solution.count),
            "calendar_bars": int(target_count),
            "converged": bool(solution.converged),
            "bucket_turnover_p5": float(np.percentile(sums, 5)) if sums.size else None,
            "bucket_turnover_p50": float(np.percentile(sums, 50)) if sums.size else None,
            "bucket_turnover_p95": float(np.percentile(sums, 95)) if sums.size else None,
            "single_bar_buckets": float(np.mean(np.diff(np.concatenate(([0], edges))) == 1))
            if edges.size
            else None,
        }

    factors = list(SCALES.values())
    combined: dict[str, float] = {}
    agreement: dict[str, int] = {}
    per_measure: dict[str, dict] = {}

    for measure in ("rank_autocorrelation", "hit_rate"):
        observed, null = paired_null_draws(
            returns_5m=returns,
            quote_volume=quote_volume,
            edges_by_scale=edges_by_scale,
            calendar_factors=factors,
            measure=measure,
            draws=DRAWS,
            mean_block=float(block),
            seed=SEED,
        )
        pooled = combine_scales(observed, null)
        combined[measure] = pooled.p_value
        agreement[measure] = pooled.sign_agreement
        per_measure[measure] = {
            "deltas": observed.tolist(),
            "statistic": pooled.statistic,
            "p_value": pooled.p_value,
            "sign_agreement": pooled.sign_agreement,
        }

    dollar_delta, dollar_forward, calendar_delta, calendar_forward = {}, {}, {}, {}
    for factor in factors:
        dollar_delta[factor], dollar_forward[factor] = _delta_and_forward(
            aggregate_by_edges(frame, edges_by_scale[factor])
        )
        calendar_delta[factor], calendar_forward[factor] = _delta_and_forward(
            aggregate_calendar(frame, factor)
        )

    delta_observed, delta_null = delta_paired_null_draws(
        dollar_delta=dollar_delta,
        dollar_forward=dollar_forward,
        calendar_delta=calendar_delta,
        calendar_forward=calendar_forward,
        factors=factors,
        draws=DRAWS,
        mean_block=float(block),
        seed=SEED,
    )
    pooled_delta = combine_scales(delta_observed, delta_null)
    combined["delta_power"] = pooled_delta.p_value
    agreement["delta_power"] = pooled_delta.sign_agreement
    per_measure["delta_power"] = {
        "deltas": delta_observed.tolist(),
        "statistic": pooled_delta.statistic,
        "p_value": pooled_delta.p_value,
        "sign_agreement": pooled_delta.sign_agreement,
    }

    corroboration = {}
    kurtosis_reduced = 0
    for label, factor in SCALES.items():
        dollar = aggregate_by_edges(frame, edges_by_scale[factor])
        calendar = aggregate_calendar(frame, factor)
        dollar_r = log_returns(dollar["close"].to_numpy())
        calendar_r = log_returns(calendar["close"].to_numpy())
        k_dollar = excess_kurtosis(dollar_r)
        k_calendar = excess_kurtosis(calendar_r)
        kurtosis_reduced += int(k_dollar < k_calendar)
        corroboration[label] = {
            "kurtosis_dollar": k_dollar,
            "kurtosis_calendar": k_calendar,
            "variance_ratio_dollar": {str(q): variance_ratio(dollar_r, q) for q in (2, 4, 8)},
            "variance_ratio_calendar": {
                str(q): variance_ratio(calendar_r, q) for q in (2, 4, 8)
            },
            "hit_rate_dollar": direction_hit_rate(dollar_r).rate,
            "hit_rate_calendar": direction_hit_rate(calendar_r).rate,
            "rank_autocorr_dollar": rank_autocorrelation(dollar_r),
            "rank_autocorr_calendar": rank_autocorrelation(calendar_r),
            "median_duration_hours": float(np.median(dollar["duration_ms"])) / 3_600_000,
        }

    # D4: the coupling premise the three-layer narrative rests on.
    spread = corwin_schultz_spread(frame["high"].to_numpy(), frame["low"].to_numpy())
    hourly = aggregate_calendar(frame, 12)
    hourly_spread = np.add.reduceat(
        spread[: (len(spread) // 12) * 12], np.arange(0, (len(spread) // 12) * 12, 12)
    ) / 12.0
    duration_proxy = 1.0 / hourly["quote_volume"].to_numpy()[: hourly_spread.size]
    premise = {
        "spread_vs_inverse_turnover_spearman": rank_predictive_power(
            duration_proxy, hourly_spread
        ),
        "median_spread_bps": float(np.median(spread) * 10_000),
    }

    report = evaluate_gates(
        combined=combined,
        sign_agreement=agreement,
        kurtosis_reduced_scales=kurtosis_reduced,
        n_scales=len(SCALES),
    )

    result = {
        "label": "doge-dollar-clock-diagnosis-v1",
        "window": {"start": EXPLORE_START, "end": EXPLORE_END},
        "bars": len(frame),
        "fingerprints": {"ohlcv": fingerprint(frame)},
        "versions": {
            "scales": SCALES,
            "draws": DRAWS,
            "seed": SEED,
            "block_length": block,
            "sidak_alpha": SIDAK_ALPHA,
        },
        "fidelity": fidelity,
        "measures": per_measure,
        "corroboration": corroboration,
        "coupling_premise": premise,
        "gates": {
            "g1_significance": report.g1_passed,
            "g2_kurtosis_sanity": report.g2_passed,
            "g3_sign_consistency": report.g3_passed,
            "kurtosis_reduced_scales": kurtosis_reduced,
            "winning_measure": report.winning_measure,
        },
        "verdict": report.verdict,
        "holdout_recorded": False,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    args = parser.parse_args(argv)

    result = run(args.db, Path(args.out))
    print(f"verdict={result['verdict']} bars={result['bars']}")
    print(f"fingerprint={result['fingerprints']['ohlcv']}")
    for name, payload in result["measures"].items():
        print(
            f"  {name:<22} p={payload['p_value']:.4f} "
            f"signs={payload['sign_agreement']}/{len(SCALES)}"
        )
    print(f"gates: {result['gates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_diagnose_coordinate_runner.py -v`
Expected: 3 passed

- [ ] **Step 5: 全仓测试 + lint**

```bash
.venv/bin/python -m pytest -q -m "not integration"
.venv/bin/python -m ruff check cq scripts tests
.venv/bin/python -m ruff format --check cq scripts tests
```

Expected: 全部通过。既有测试数不得下降。

- [ ] **Step 6: 提交**

```bash
git add scripts/__init__.py scripts/diagnose_coordinate.py tests/test_diagnose_coordinate_runner.py
git commit -m "feat(research): D-phase runner for the dollar-clock coordinate diagnosis"
```

---

### Task 12: PROTOCOL 预注册（必须先于跑诊断）

D3 的 Šidák 阈值与 G3 符号一致性，事后再定就一文不值。本任务必须在 Task 13 之前 commit。

**Files:**
- Create: `docs/research/doge-5m/DOLLAR_CLOCK_PROTOCOL_2026-07-30.md`

- [ ] **Step 1: 取得数据指纹与 block 长度（不看任何测度结果）**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
from cq.data.store import Store
from cq.research.coordinate_diagnostics import select_block_length
from cq.research.microstructure import log_returns
from cq.research.split import to_ms
from scripts.diagnose_coordinate import EXPLORE_END, EXPLORE_START, INST_ID, TIMEFRAME, assert_contiguous, fingerprint

with Store("data/cq.db") as store:
    frame = store.load_ohlcv(INST_ID, TIMEFRAME, to_ms(EXPLORE_START), to_ms(EXPLORE_END))
assert_contiguous(frame)
print("bars       ", len(frame))
print("fingerprint", fingerprint(frame))
print("block      ", select_block_length(log_returns(frame["close"].to_numpy())))
EOF
```

只记录这三个数字。**不得**在此处计算任何测度——那等于先看答案再写协议。

- [ ] **Step 2: 写 PROTOCOL**

文档必须逐条写死，内容取自本计划的 Global Constraints 与 spec §4，并填入 Step 1 的三个实测值：

1. 数据契约：标的、窗口、列、连续性断言、零量 bar 规则、指纹（实测值）
2. 时钟构造：封桶规则三条、`V_s` 二分与容差、四尺度因子
3. 测度定义：三个主测度、三个佐证测度、`δ` 与收益的精确定义
4. null 构造：两类 null 各自的零假设与实现、block 长度（实测值）、`B=2000`、`seed=0`
5. 闸门 G1/G2/G3 与阈值 `0.016952`、`≥3/4` 符号一致
6. 裁决语义：PASS / CLOSED / INVALID 三者的含义，其中 INVALID 明确表示时钟实现有 bug 而非市场结论
7. D4 附加诊断清单（不设门），含咬合前提检验

- [ ] **Step 3: 提交（在跑诊断之前）**

```bash
git add docs/research/doge-5m/DOLLAR_CLOCK_PROTOCOL_2026-07-30.md
git commit -m "docs(research): pre-register the dollar-clock coordinate diagnosis protocol"
```

---

### Task 13: 跑诊断并写 RESULTS

**Files:**
- Create: `docs/research/doge-5m/DOLLAR_CLOCK_RESULTS_2026-07-30.md`
- Create: `reports/research/doge_dollar_clock_diagnose.json`

- [ ] **Step 1: 确认 PROTOCOL 已提交**

```bash
git log --oneline -1 -- docs/research/doge-5m/DOLLAR_CLOCK_PROTOCOL_2026-07-30.md
```

Expected: 有一条 commit。若为空，回到 Task 12——**不得先跑后写协议**。

- [ ] **Step 2: 跑诊断**

```bash
.venv/bin/python scripts/diagnose_coordinate.py --db data/cq.db
```

Expected: 打印 verdict 与三个主测度的 p 值；写出 `reports/research/doge_dollar_clock_diagnose.json`。

**预期耗时 25–30 分钟**（实测外推：bootstrap 索引生成约 4 分钟，三个测度各 2000 draws × 四尺度 Spearman 约 20 分钟）。不是卡死，不要中途 kill。建议 `--out` 先写到临时路径试跑一次小 `DRAWS` 验证管线通畅，再跑正式的。

- [ ] **Step 3: 核对指纹**

JSON 里的 `fingerprints.ohlcv` 必须与 PROTOCOL 中记录的一致。不一致说明诊断跑的不是预注册的那份数据，**作废重来**。

- [ ] **Step 4: 写 RESULTS**

必须包含：

1. **裁决**（PASS / CLOSED / INVALID）与三道闸门逐条的通过情况
2. **保真度报告**：每尺度的 `M_s`/`N_s`、`V_s`、桶实际成交额 p5/p50/p95、单根 5m 成桶占比。这是 spec 承诺要报告的硬伤，不得省略
3. **三个主测度**的四尺度 `Δ_s`、合并统计量、p 值、符号一致数
4. **参数佐证**：VR、峰度、命中率的日历 vs 成交额对照。**两套背离时写进结论**——背离说明信号存在但被尾部吞掉，这是可操作情报
5. **D4 咬合前提检验结论**：若「价差 ~ 活跃度」不成立，明确写出「§2.4 三层咬合叙事的前提不成立，S 阶段设计须改写」
6. 若裁决为 CLOSED：明确写出「DOGE 现货 5m 在日历与成交额两个正交坐标系下均无可利用结构」，并说明这是新增证据而非重复检验
7. 若裁决为 INVALID：写清是时钟实现问题，列出待排查项，**不得**记为市场结论

- [ ] **Step 5: 提交**

```bash
git add docs/research/doge-5m/DOLLAR_CLOCK_RESULTS_2026-07-30.md reports/research/doge_dollar_clock_diagnose.json
git commit -m "research(doge): adjudicate the dollar-clock coordinate diagnosis"
```

- [ ] **Step 6: 更新记忆**

在 `/home/roler/.claude/projects/-home-roler-Code-CQuant/memory/` 写一条 `type: project` 记忆，记录裁决与关键数字，并在 `MEMORY.md` 加索引行。同时修正 `doge-5m-dlsr-2026-07-24.md` 中已过时的「GATE-BLOCKED / 校准闸门未开」条目——闸门已被 `1718535` 移除。

---

## Self-Review

**1. Spec 覆盖检查**

| spec 章节 | 覆盖任务 |
|---|---|
| §4 D0 数据契约（连续性、零量、指纹、open 不作特征） | Task 11（断言与指纹）、Task 3（零量吸收） |
| §4 D0 统一定义（对数收益、δ、命中率剔零） | Task 1、Task 6 |
| §4 D1 时钟构造（封桶三条、二分、聚合、Δt） | Task 3、4、5 |
| §4 D1 保真度报告 | Task 11 `fidelity`、Task 13 Step 4.2 |
| §4 D2 六个测度 | Task 6、7 |
| §4 D3 两个 null | Task 10 `paired_null_draws`、Task 11 δ null |
| §4 D3 block 长度预注册规则 | Task 8 `select_block_length`、Task 12 Step 1 |
| §4 D3 闸门 G1/G2/G3 | Task 9 `evaluate_gates` |
| §4 D4 咬合前提检验 | Task 11 `coupling_premise`、Task 13 Step 4.5 |
| §7 模块划分与测试（含 null 元测试） | Task 1–11，元测试在 Task 10 |
| §7 产出物 | Task 12、13 |
| §9 实施范围（仅 D 阶段） | 全计划止于 Task 13，不含 S/V |

无缺口。S 阶段（spec §5）与 V 阶段（spec §6）按 spec §9 明确排除在本计划外。

**2. 占位符扫描**

无 TBD/TODO；每个代码步骤都给出可运行代码；无「同 Task N」式省略。Task 12、13 是文档与执行任务，其「写文档」步骤给出了逐条必含内容清单而非泛泛指示。

**3. 类型一致性**

- `bucket_edges` 在 Task 3 定义返回 `np.ndarray[int64]`，Task 4/5/10/11 一致按右开端索引使用
- `solve_bucket_size` 返回 `BucketSolution`，Task 11 用 `.target_value` / `.count` / `.converged`，与 Task 4 定义一致
- `aggregate_by_edges` / `aggregate_calendar` 列集合在 Task 5 固定为 8 列，Task 11 使用 `high/low/close/volume/quote_volume/duration_ms`，均在其中
- `combine_scales` 返回 `Combined(statistic, p_value, sign_agreement)`，Task 11 三处使用一致
- `evaluate_gates` 参数名 `combined` / `sign_agreement` / `kurtosis_reduced_scales` / `n_scales` 在 Task 9 与 Task 11 一致
- `_measure` 仅支持 `rank_autocorrelation` 与 `hit_rate`；`delta_power` 走 `delta_paired_null_draws`（因其 null 不同），此处不重名冲突
- `delta_paired_null_draws` 的四个 dict 参数均以 `factor`（`int`）为键，与 `edges_by_scale` 的键类型一致；Task 11 构造它们时用的正是 `factors = list(SCALES.values())`
- `BAR_MS` 在 `dollar_clock.py` 定义一次，Task 11 从该模块导入，未重复定义
