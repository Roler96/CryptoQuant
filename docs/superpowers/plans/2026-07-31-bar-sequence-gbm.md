# Bar-Sequence-GBM Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the measurement apparatus for `docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md` — load the frozen DOGE-USDT spot 5m explore window, turn raw per-bar return sequences into features, run a 5-fold calendar-anchored walk-forward comparing a linear baseline against a gradient-boosted model, and emit a gated verdict as JSON.

**Architecture:** A `cq/research/bar_sequence/` package with one file per concern (data loading, windowing, fold definitions, model selection, statistics/gating, leakage sanity checks, orchestration), wired into the CLI as `cq research bar-sequence-gbm run`. Every module is pure functions over numpy arrays except the `Store`-touching loader and the CLI wiring, so the statistical core is testable without a database.

**Tech Stack:** numpy, pandas (already a dependency), scipy.stats.spearmanr (already a dependency), scikit-learn (**new** dependency — `LogisticRegression` + `HistGradientBoostingClassifier`, added in Task 1).

## Global Constraints

- Every threshold, boundary, and formula below is copied verbatim from `docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md`. If a task's code disagrees with the protocol, the protocol wins — stop and flag it, do not silently pick one.
- `EXPLORE_START = 2021-01-01T00:00:00Z`, `FORWARD_FREEZE = 2025-06-01T00:00:00Z` (ms epoch). The validate window `2025-06-01 → 2027-06-01` must never be read by any code this plan adds.
- Frozen raw fingerprint (pre-filter): `3122d7bd0c97aeda`. Frozen degenerate-bar drop count: `520`. Frozen post-filter bar count: `463640`.
- G4 cost-wall floor: `0.0726`. Šidák per-test alpha: `1 - (1 - 0.05) ** (1/3)` (family size 3, for the three feature sets).
- Lookback grid `N ∈ {10, 20, 40}`. Logistic `C ∈ {0.01, 0.1, 1.0}`. GBM `max_depth ∈ {2,3,4}`, `min_samples_leaf ∈ {500,1000}`, `learning_rate=0.05` fixed, `max_iter=500`, `n_iter_no_change=30`.
- Follow existing repo conventions: flat `tests/test_*.py` (not nested by package), `Store(tmp_path / "test.db")` fixture pattern, `commands.register(subparsers)` CLI wiring per subsystem.

---

### Task 1: Add scikit-learn as a project dependency

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `sklearn.linear_model.LogisticRegression`, `sklearn.ensemble.HistGradientBoostingClassifier` importable in the venv, used by Task 7.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, in the `dependencies` list, add a line after `"pydantic-settings>=2.0.0,<3.0.0",`:

```toml
    "scikit-learn>=1.3.0,<2.0.0",
```

- [ ] **Step 2: Install and verify**

Run: `pip install -e .`
Then: `python3 -c "from sklearn.linear_model import LogisticRegression; from sklearn.ensemble import HistGradientBoostingClassifier; print('ok')"`
Expected: prints `ok` with no import error.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add scikit-learn for the bar-sequence-GBM study"
```

---

### Task 2: Rebuild `cq/research/split.py` (explore window + data fingerprint)

The research subsystem was deleted wholesale on 2026-07-31 (`a51cb62`). This task rebuilds only the two primitives this study needs — not the full assortment that existed before.

**Files:**
- Create: `cq/research/split.py`
- Test: `tests/test_research_split.py`

**Interfaces:**
- Produces: `explore_window() -> tuple[int, int]` (start_ms, end_ms), `data_fingerprint(frame: pd.DataFrame) -> str`. Used by Task 3.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_research_split.py
import hashlib
import struct
from datetime import datetime, timezone

import pandas as pd

from cq.research.split import data_fingerprint, explore_window


def test_explore_window_matches_frozen_boundary():
    start_ms, end_ms = explore_window()
    assert start_ms == int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert end_ms == int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)


def test_fingerprint_matches_hand_computed_hash():
    frame = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.5, 1.5],
            "close": [1.2, 2.2],
            "volume": [10.0, 20.0],
        },
        index=pd.to_datetime([1_700_000_000_000, 1_700_000_300_000], unit="ms", utc=True),
    )

    expected = hashlib.sha256()
    for ts, o, h, low_, c in [
        (1_700_000_000_000, 1.0, 1.5, 0.5, 1.2),
        (1_700_000_300_000, 2.0, 2.5, 1.5, 2.2),
    ]:
        expected.update(struct.pack("<qdddd", ts, o, h, low_, c))

    assert data_fingerprint(frame) == expected.hexdigest()[:16]


def test_fingerprint_is_order_independent_of_input_but_not_of_ts():
    # Feeding rows out of ts order must not change the fingerprint -- the
    # function sorts internally.
    frame = pd.DataFrame(
        {"open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.5, 1.5], "close": [1.2, 2.2], "volume": [10.0, 20.0]},
        index=pd.to_datetime([1_700_000_300_000, 1_700_000_000_000], unit="ms", utc=True),
    )
    sorted_frame = frame.sort_index()
    assert data_fingerprint(frame) == data_fingerprint(sorted_frame)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research_split.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.split'`

- [ ] **Step 3: Implement**

```python
# cq/research/split.py
"""Explore/validate window boundary and data fingerprinting.

Rebuilt 2026-07-31 after the research subsystem purge (`a51cb62`) -- only
the two primitives the current bar-sequence-GBM study needs, not the full
assortment that existed before. See project memory `research-reset-2026-07-23`
for why FORWARD_FREEZE is 2025-06-01 and not the earlier 2026-07-20.
"""

from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone

import pandas as pd

EXPLORE_START = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
FORWARD_FREEZE = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
VALIDATE_END = int(datetime(2027, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)


def explore_window() -> tuple[int, int]:
    """The frozen explore boundary: [EXPLORE_START, FORWARD_FREEZE)."""
    return EXPLORE_START, FORWARD_FREEZE


def data_fingerprint(frame: pd.DataFrame) -> str:
    """A reproducibility fingerprint over (ts, open, high, low, close), ts-ordered.

    Truncated to 16 hex characters, matching the convention frozen in
    docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md.
    """
    ordered = frame.sort_index()
    ts_ms = ordered.index.astype("int64") // 1_000_000
    digest = hashlib.sha256()
    for ts, o, h, low_, c in zip(
        ts_ms, ordered["open"], ordered["high"], ordered["low"], ordered["close"]
    ):
        digest.update(struct.pack("<qdddd", int(ts), float(o), float(h), float(low_), float(c)))
    return digest.hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research_split.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add cq/research/split.py tests/test_research_split.py
git commit -m "feat(research): rebuild explore-window and fingerprint primitives"
```

---

### Task 3: `cq/research/bar_sequence/data.py` — load and validate the frozen bars

**Files:**
- Create: `cq/research/bar_sequence/__init__.py` (empty)
- Create: `cq/research/bar_sequence/data.py`
- Test: `tests/test_bar_sequence_data.py`

**Interfaces:**
- Consumes: `cq.research.split.explore_window()`, `cq.research.split.data_fingerprint()`; `cq.data.store.Store.load_ohlcv(inst_id, timeframe, start_ms, end_ms) -> pd.DataFrame` (existing).
- Produces: `load_explore_bars(store) -> tuple[pd.DataFrame, int]` (filtered frame, dropped-bar count); `log_returns(frame) -> np.ndarray`. Used by Task 4 and Task 10.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bar_sequence_data.py
import numpy as np
import pandas as pd
import pytest

from cq.data.store import Store
from cq.research.bar_sequence.data import (
    FingerprintMismatchError,
    load_explore_bars,
    log_returns,
)


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def _rows(inst_id, ts_start_ms, closes, volumes):
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        ts = ts_start_ms + i * 300_000  # 5m bars
        o = h = low = c
        rows.append((inst_id, ts, o, h, low, c, v, c * v))
    return rows


def test_load_explore_bars_drops_degenerate_bars_and_reports_count(store):
    # Bar index 2 is a synthetic flat/zero-volume print (OKX outage style).
    closes = [1.0, 1.01, 1.01, 1.02, 1.03]
    volumes = [10.0, 10.0, 0.0, 10.0, 10.0]
    store.upsert_ohlcv(_rows("DOGE-USDT", 1_609_459_200_000, closes, volumes))

    with pytest.raises(FingerprintMismatchError):
        # Synthetic data will never match the frozen real-data fingerprint --
        # this proves the check actually fires rather than being skipped.
        load_explore_bars(store)


def test_log_returns_alignment():
    frame = pd.DataFrame({"close": [1.0, 1.1, 0.99]})
    r = log_returns(frame)
    assert len(r) == 2
    assert r[0] == pytest.approx(np.log(1.1 / 1.0))
    assert r[1] == pytest.approx(np.log(0.99 / 1.1))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bar_sequence_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.bar_sequence'`

- [ ] **Step 3: Implement**

```python
# cq/research/bar_sequence/data.py
"""Load and validate the frozen DOGE-USDT spot 5m explore-window bars for the
bar-sequence-GBM study.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md §1: the raw
fingerprint check must run BEFORE degenerate-bar filtering, so a source-data
change and a filtering bug produce distinguishable failures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cq.data.store import Store
from cq.research.split import data_fingerprint, explore_window

INST_ID = "DOGE-USDT"
TIMEFRAME = "5m"
EXPECTED_RAW_FINGERPRINT = "3122d7bd0c97aeda"
EXPECTED_RAW_BAR_COUNT = 464_160
EXPECTED_DEGENERATE_DROP_COUNT = 520


class FingerprintMismatchError(RuntimeError):
    """The raw pull does not match the frozen protocol snapshot."""


def load_explore_bars(store: Store) -> tuple[pd.DataFrame, int]:
    """The frozen explore-window bars, degenerate bars dropped.

    Returns (filtered_frame, dropped_count). Raises FingerprintMismatchError
    if the raw pull (before filtering) does not match the frozen protocol
    snapshot.
    """
    start_ms, end_ms = explore_window()
    raw = store.load_ohlcv(INST_ID, TIMEFRAME, start_ms=start_ms, end_ms=end_ms)

    fingerprint = data_fingerprint(raw)
    if fingerprint != EXPECTED_RAW_FINGERPRINT:
        raise FingerprintMismatchError(
            f"raw explore-window fingerprint {fingerprint} != frozen "
            f"{EXPECTED_RAW_FINGERPRINT} ({len(raw)} raw bars, expected "
            f"{EXPECTED_RAW_BAR_COUNT}) -- protocol requires re-freezing "
            f"before continuing, not silently proceeding"
        )

    filtered = raw[(raw["high"] > raw["low"]) & (raw["volume"] > 0)]
    dropped = len(raw) - len(filtered)
    return filtered, dropped


def log_returns(frame: pd.DataFrame) -> np.ndarray:
    """r[k] = log(close_{k+1} / close_k) for k=0..len(frame)-2."""
    closes = frame["close"].to_numpy()
    return np.log(closes[1:] / closes[:-1])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bar_sequence_data.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Verify against the real database and freeze the drop count**

Run:
```bash
python3 -c "
from cq.data.store import Store
from cq.research.bar_sequence.data import load_explore_bars
with Store() as store:
    frame, dropped = load_explore_bars(store)
    print('bars:', len(frame), 'dropped:', dropped)
"
```
Expected: `bars: 463640 dropped: 520` (matches the frozen protocol numbers exactly — if it
doesn't, STOP and reconcile with the protocol document before continuing; do not adjust the
constants to match a different result).

- [ ] **Step 6: Commit**

```bash
git add cq/research/bar_sequence/__init__.py cq/research/bar_sequence/data.py tests/test_bar_sequence_data.py
git commit -m "feat(research): load and fingerprint-validate the frozen explore bars"
```

---

### Task 4: `cq/research/bar_sequence/features.py` — windowing and the alignment contract

**Files:**
- Create: `cq/research/bar_sequence/features.py`
- Test: `tests/test_bar_sequence_features.py`

**Interfaces:**
- Consumes: a 1-D `np.ndarray` of returns (from Task 3's `log_returns`).
- Produces: `build_windows(returns, N) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]` giving `(k, sign_window, ret_window, label)`; `standardize(ret_window, train_rows) -> np.ndarray`. Used by Task 6 (folds) and Task 7 (models).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bar_sequence_features.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bar_sequence_features.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.bar_sequence.features'`

- [ ] **Step 3: Implement**

```python
# cq/research/bar_sequence/features.py
"""Per-bar return windowing and the feature/label alignment contract.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md §3: for a
returns array with returns[k] = r_{k+1}, the decision point k uses the past N
returns ending at k (returns[k-N+1:k+1]) and is labeled with returns[k+1] --
the next bar's return, unavailable at decision time.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def build_windows(
    returns: np.ndarray, N: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(k, sign_window, ret_window, label) for every valid decision point.

    k[j] is the return-array index of the j-th decision point (0-indexed,
    returns[k] = r_{k+1}). sign_window[j] / ret_window[j] are the N returns
    ending at k[j], in chronological order. label[j] = returns[k[j] + 1].
    """
    M0 = len(returns)
    if N < 1 or N > M0 - 2:
        raise ValueError(
            f"N={N} leaves no valid decision points for {M0} returns "
            f"(need N <= len(returns) - 2)"
        )

    windows = sliding_window_view(returns, N)  # windows[j] = returns[j:j+N]
    # windows[j] ends at k = j + N - 1. The last row (k = M0-1) has no label
    # (would need returns[M0], out of range), so it is dropped.
    usable = windows[:-1]
    k = np.arange(N - 1, M0 - 1)
    label = returns[k + 1]
    return k, np.sign(usable), usable, label


def standardize(ret_window: np.ndarray, train_rows: np.ndarray) -> np.ndarray:
    """Z-score ret_window using mean/std computed only over train_rows.

    Applying train-only statistics to the full array (train and test rows
    alike) is what keeps the walk-forward folds from leaking test-set
    statistics into the features.
    """
    train_values = ret_window[train_rows]
    mu = train_values.mean()
    sigma = train_values.std(ddof=1)
    return (ret_window - mu) / sigma
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bar_sequence_features.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add cq/research/bar_sequence/features.py tests/test_bar_sequence_features.py
git commit -m "feat(research): windowing and the feature/label alignment contract"
```

---

### Task 5: Alignment sanity check on a synthetic monotonic series (protocol §7.3)

This is the protocol's required regression test — a synthetic series where the "expected"
model behavior is analytically known, not just "runs on real data and looks plausible."

**Files:**
- Create: `tests/test_bar_sequence_alignment_sanity.py`

**Interfaces:**
- Consumes: `cq.research.bar_sequence.features.build_windows` (Task 4).

- [ ] **Step 1: Write the test**

```python
# tests/test_bar_sequence_alignment_sanity.py
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
    returns[0::2] = base
    returns[1::2] = -base

    k, sign_w, ret_w, label = build_windows(returns, N=3)

    last_col_sign = sign_w[:, -1]
    label_sign = np.sign(label)
    assert np.all(last_col_sign == -label_sign)

    last_col_ret = ret_w[:, -1]
    np.testing.assert_allclose(last_col_ret, -label)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_bar_sequence_alignment_sanity.py -v`
Expected: PASS. If it fails, the bug is in Task 4's `build_windows`, not in this test — go
back and fix the indexing, do not loosen this assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/test_bar_sequence_alignment_sanity.py
git commit -m "test(research): alignment sanity check on a synthetic reversal series"
```

---

### Task 6: `cq/research/bar_sequence/folds.py` — calendar-anchored walk-forward folds

**Files:**
- Create: `cq/research/bar_sequence/folds.py`
- Test: `tests/test_bar_sequence_folds.py`

**Interfaces:**
- Consumes: `k` array and decision timestamps derived from a filtered frame's index (Task 3/4).
- Produces: `FOLDS: tuple[Fold, ...]` (5 frozen calendar boundaries); `fold_masks(decision_ts, fold) -> tuple[np.ndarray, np.ndarray]` (train_mask, test_mask over the `k` array); `assert_no_embargo_violation(decision_ts, fold)`. Used by Task 10.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bar_sequence_folds.py
from datetime import datetime, timezone

import numpy as np
import pytest

from cq.research.bar_sequence.folds import FOLDS, assert_no_embargo_violation, fold_masks


def _ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def test_five_folds_are_frozen_and_contiguous_test_windows():
    assert len(FOLDS) == 5
    expected_test_starts = [
        _ms(2022, 7, 1),
        _ms(2023, 2, 1),
        _ms(2023, 9, 1),
        _ms(2024, 4, 1),
        _ms(2024, 11, 1),
    ]
    expected_test_ends = [
        _ms(2023, 2, 1),
        _ms(2023, 9, 1),
        _ms(2024, 4, 1),
        _ms(2024, 11, 1),
        _ms(2025, 6, 1),
    ]
    assert [f.test_start_ms for f in FOLDS] == expected_test_starts
    assert [f.test_end_ms for f in FOLDS] == expected_test_ends
    # Each fold's train window ends exactly one day before its test window
    # starts -- that one-day gap IS the embargo (protocol §5).
    for fold in FOLDS:
        assert fold.test_start_ms - fold.train_end_ms == 24 * 60 * 60 * 1000


def test_fold_masks_split_decision_points_by_timestamp():
    fold = FOLDS[0]
    decision_ts = np.array(
        [
            fold.train_end_ms - 1,  # last train ms, included
            fold.train_end_ms,  # inside the embargo gap, excluded from both
            fold.test_start_ms,  # first test ms, included
            fold.test_end_ms,  # exclusive end, excluded
        ]
    )
    train_mask, test_mask = fold_masks(decision_ts, fold)
    np.testing.assert_array_equal(train_mask, [True, False, False, False])
    np.testing.assert_array_equal(test_mask, [False, False, True, False])


def test_assert_no_embargo_violation_catches_a_leaking_train_set(monkeypatch):
    fold = FOLDS[0]
    leaking_ts = np.array([fold.train_end_ms])  # inside the embargo gap
    with pytest.raises(AssertionError):
        assert_no_embargo_violation(leaking_ts, fold)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bar_sequence_folds.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.bar_sequence.folds'`

- [ ] **Step 3: Implement**

```python
# cq/research/bar_sequence/folds.py
"""The 5 frozen calendar-anchored walk-forward folds.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md §5. Boundaries
are half-open [start, end). The one-day gap between a fold's train_end_ms and
test_start_ms IS the embargo -- it is not applied again on top of these numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np


@dataclass(frozen=True)
class Fold:
    train_start_ms: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int


def _ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


_TRAIN_START = _ms(2021, 1, 1)

FOLDS: tuple[Fold, ...] = (
    Fold(_TRAIN_START, _ms(2022, 6, 30), _ms(2022, 7, 1), _ms(2023, 2, 1)),
    Fold(_TRAIN_START, _ms(2023, 1, 31), _ms(2023, 2, 1), _ms(2023, 9, 1)),
    Fold(_TRAIN_START, _ms(2023, 8, 31), _ms(2023, 9, 1), _ms(2024, 4, 1)),
    Fold(_TRAIN_START, _ms(2024, 3, 31), _ms(2024, 4, 1), _ms(2024, 11, 1)),
    Fold(_TRAIN_START, _ms(2024, 10, 31), _ms(2024, 11, 1), _ms(2025, 6, 1)),
)


def fold_masks(decision_ts_ms: np.ndarray, fold: Fold) -> tuple[np.ndarray, np.ndarray]:
    """Boolean masks (train_mask, test_mask) over an array of decision timestamps."""
    train_mask = (decision_ts_ms >= fold.train_start_ms) & (decision_ts_ms < fold.train_end_ms)
    test_mask = (decision_ts_ms >= fold.test_start_ms) & (decision_ts_ms < fold.test_end_ms)
    return train_mask, test_mask


def assert_no_embargo_violation(decision_ts_ms: np.ndarray, fold: Fold) -> None:
    """Raise if any timestamp claimed as training data falls in the embargo gap
    or inside the test window itself."""
    violating = (decision_ts_ms >= fold.train_end_ms) & (decision_ts_ms < fold.test_end_ms)
    assert not violating.any(), (
        f"{violating.sum()} decision points fall inside the embargo/test window "
        f"[{fold.train_end_ms}, {fold.test_end_ms}) but were passed as training data"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bar_sequence_folds.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add cq/research/bar_sequence/folds.py tests/test_bar_sequence_folds.py
git commit -m "feat(research): frozen calendar-anchored walk-forward folds"
```

---

### Task 7: `cq/research/bar_sequence/models.py` — nested hyperparameter selection

**Files:**
- Create: `cq/research/bar_sequence/models.py`
- Test: `tests/test_bar_sequence_models.py`

**Interfaces:**
- Consumes: `cq.research.bar_sequence.features.build_windows`, `standardize`; `scipy.stats.spearmanr`.
- Produces: `select_fold_models(returns, decision_ts_ms, fold, feature_set) -> FoldFit` where `FoldFit` carries the chosen `N`, fitted logistic + GBM models, and their test-fold predictions/labels. Used by Task 8 (stats) and Task 10 (runner).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bar_sequence_models.py
import numpy as np
import pytest

from cq.research.bar_sequence.folds import Fold
from cq.research.bar_sequence.models import select_fold_models


def _synthetic_returns(n, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(scale=0.001, size=n)


def _decision_ts_for(returns, N, fold, ms_per_bar=300_000):
    # Enough bars, spaced 5m apart starting at the fold's train_start, to
    # populate both the train and test windows of the given fold.
    n_bars = len(returns) + 1
    return fold.train_start_ms + np.arange(1, n_bars) * ms_per_bar


@pytest.mark.parametrize("feature_set", ["sign", "ret", "both"])
def test_select_fold_models_returns_predictions_for_the_test_fold(feature_set):
    fold = Fold(0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000)
    returns = _synthetic_returns(400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000

    fit = select_fold_models(returns, decision_ts_ms, fold, feature_set)

    assert fit.lookback_n in (10, 20, 40)
    assert len(fit.test_label) == len(fit.logistic_pred) == len(fit.gbm_pred)
    assert len(fit.test_label) > 0
    assert set(np.unique(np.sign(fit.logistic_pred - 0.5))) <= {-1.0, 0.0, 1.0}


def test_select_fold_models_rejects_unknown_feature_set():
    fold = Fold(0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000)
    returns = _synthetic_returns(400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000
    with pytest.raises(ValueError):
        select_fold_models(returns, decision_ts_ms, fold, "not-a-real-feature-set")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bar_sequence_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.bar_sequence.models'`

- [ ] **Step 3: Implement**

```python
# cq/research/bar_sequence/models.py
"""Nested walk-forward hyperparameter selection.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md §4: within a
fold's training window, the last 15% (chronologically) is held out as an
inner validation set to pick N and the model hyperparameters; the outer test
fold never participates in that choice. N is shared between the logistic
baseline and the GBM candidate within a fold, selected by the GBM's inner-
validation rank-IC (the GBM is the candidate under test; the baseline just
uses whatever input the candidate settled on, keeping the comparison
apples-to-apples per §4).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from cq.research.bar_sequence.features import build_windows, standardize
from cq.research.bar_sequence.folds import Fold, assert_no_embargo_violation, fold_masks

LOOKBACK_GRID = (10, 20, 40)
LOGISTIC_C_GRID = (0.01, 0.1, 1.0)
GBM_DEPTH_GRID = (2, 3, 4)
GBM_MIN_LEAF_GRID = (500, 1000)
INNER_VAL_FRACTION = 0.15

FEATURE_SETS = ("sign", "ret", "both")


@dataclass
class FoldFit:
    lookback_n: int
    test_label: np.ndarray
    logistic_pred: np.ndarray
    gbm_pred: np.ndarray


def _features_for(feature_set: str, sign_window: np.ndarray, ret_z: np.ndarray) -> np.ndarray:
    if feature_set == "sign":
        return sign_window
    if feature_set == "ret":
        return ret_z
    if feature_set == "both":
        return np.concatenate([sign_window, ret_z], axis=1)
    raise ValueError(f"unknown feature_set {feature_set!r}, expected one of {FEATURE_SETS}")


def _rank_ic(pred: np.ndarray, label: np.ndarray) -> float:
    ic, _ = spearmanr(pred, label)
    return 0.0 if np.isnan(ic) else ic


def _inner_split(train_positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Chronological 85/15 split of an already-time-ordered index array."""
    cutoff = int(len(train_positions) * (1 - INNER_VAL_FRACTION))
    return train_positions[:cutoff], train_positions[cutoff:]


def select_fold_models(
    returns: np.ndarray, decision_ts_ms: np.ndarray, fold: Fold, feature_set: str
) -> FoldFit:
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"unknown feature_set {feature_set!r}, expected one of {FEATURE_SETS}")

    best = None  # (inner_val_ic, N, gbm_params, gbm_model)
    best_logistic = None  # (inner_val_ic, C)

    for N in LOOKBACK_GRID:
        k, sign_window, ret_window, label = build_windows(returns, N)
        decision_ts_for_k = decision_ts_ms[k]
        train_mask, test_mask = fold_masks(decision_ts_for_k, fold)
        assert_no_embargo_violation(decision_ts_for_k[train_mask], fold)

        train_positions = np.flatnonzero(train_mask)
        if len(train_positions) < 20:
            continue  # not enough history at this N for this fold yet
        inner_train_pos, inner_val_pos = _inner_split(train_positions)

        train_rows_for_std = np.zeros(len(k), dtype=bool)
        train_rows_for_std[inner_train_pos] = True
        ret_z = standardize(ret_window, train_rows_for_std)
        X = _features_for(feature_set, sign_window, ret_z)

        for depth in GBM_DEPTH_GRID:
            for min_leaf in GBM_MIN_LEAF_GRID:
                gbm = HistGradientBoostingClassifier(
                    max_depth=depth,
                    min_samples_leaf=min_leaf,
                    learning_rate=0.05,
                    max_iter=500,
                    n_iter_no_change=30,
                    validation_fraction=None,
                )
                gbm.fit(X[inner_train_pos], (label[inner_train_pos] > 0).astype(int))
                pred = gbm.predict_proba(X[inner_val_pos])[:, 1]
                ic = _rank_ic(pred, label[inner_val_pos])
                if best is None or ic > best[0]:
                    best = (ic, N, depth, min_leaf)

    if best is None:
        raise ValueError("no lookback N in the grid had enough training history for this fold")

    _, chosen_n, chosen_depth, chosen_leaf = best
    k, sign_window, ret_window, label = build_windows(returns, chosen_n)
    decision_ts_for_k = decision_ts_ms[k]
    train_mask, test_mask = fold_masks(decision_ts_for_k, fold)
    assert_no_embargo_violation(decision_ts_for_k[train_mask], fold)

    ret_z = standardize(ret_window, train_mask)
    X = _features_for(feature_set, sign_window, ret_z)
    y = (label > 0).astype(int)

    for C in LOGISTIC_C_GRID:
        train_positions = np.flatnonzero(train_mask)
        inner_train_pos, inner_val_pos = _inner_split(train_positions)
        lr = LogisticRegression(C=C, max_iter=1000)
        lr.fit(X[inner_train_pos], y[inner_train_pos])
        pred = lr.predict_proba(X[inner_val_pos])[:, 1]
        ic = _rank_ic(pred, label[inner_val_pos])
        if best_logistic is None or ic > best_logistic[0]:
            best_logistic = (ic, C)

    final_logistic = LogisticRegression(C=best_logistic[1], max_iter=1000)
    final_logistic.fit(X[train_mask], y[train_mask])

    final_gbm = HistGradientBoostingClassifier(
        max_depth=chosen_depth,
        min_samples_leaf=chosen_leaf,
        learning_rate=0.05,
        max_iter=500,
        n_iter_no_change=30,
        validation_fraction=None,
    )
    final_gbm.fit(X[train_mask], y[train_mask])

    return FoldFit(
        lookback_n=chosen_n,
        test_label=label[test_mask],
        logistic_pred=final_logistic.predict_proba(X[test_mask])[:, 1],
        gbm_pred=final_gbm.predict_proba(X[test_mask])[:, 1],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bar_sequence_models.py -v`
Expected: PASS (4 tests). This task's fit is slower than earlier ones (grid search over 6
GBM configs per candidate N) — allow it to run a few seconds.

- [ ] **Step 5: Commit**

```bash
git add cq/research/bar_sequence/models.py tests/test_bar_sequence_models.py
git commit -m "feat(research): nested walk-forward model selection (logistic + GBM)"
```

---

### Task 8: `cq/research/bar_sequence/stats.py` — rank-IC, null, gates, verdict

**Files:**
- Create: `cq/research/bar_sequence/stats.py`
- Test: `tests/test_bar_sequence_stats.py`

**Interfaces:**
- Consumes: per-fold `(label, pred)` arrays (from Task 7's `FoldFit`).
- Produces: `rank_ic(pred, label) -> float`; `block_length(n_test) -> int`; `block_bootstrap_p(fold_labels, fold_preds, B=2000, seed=0) -> float`; `SIDAK_ALPHA`; `evaluate_gates(fold_ics, linear_fold_ics, p_value, cost_floor=0.0726) -> Verdict`. Used by Task 10.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bar_sequence_stats.py
import numpy as np
import pytest

from cq.research.bar_sequence.stats import (
    SIDAK_ALPHA,
    Verdict,
    block_bootstrap_p,
    block_length,
    evaluate_gates,
    rank_ic,
)


def test_rank_ic_matches_spearman_on_a_known_case():
    pred = np.array([0.1, 0.2, 0.3, 0.4])
    label = np.array([-1.0, -2.0, -3.0, -4.0])  # perfectly anti-monotonic
    assert rank_ic(pred, label) == pytest.approx(-1.0)


def test_block_length_uses_cube_root_heuristic():
    assert block_length(1000) == round(1000 ** (1 / 3))
    assert block_length(1) == 1  # never degenerate to zero


def test_sidak_alpha_for_family_of_three():
    assert SIDAK_ALPHA == pytest.approx(1 - (1 - 0.05) ** (1 / 3))


def test_block_bootstrap_p_is_small_for_a_strong_real_relationship():
    rng = np.random.default_rng(0)
    fold_labels = [rng.normal(size=2000) for _ in range(5)]
    # pred is a noisy but strong copy of label -- true signal, not noise.
    fold_preds = [lbl + rng.normal(scale=0.05, size=2000) for lbl in fold_labels]
    p = block_bootstrap_p(fold_labels, fold_preds, B=200, seed=0)
    assert p < 0.05


def test_block_bootstrap_p_is_large_for_unrelated_series():
    rng = np.random.default_rng(1)
    fold_labels = [rng.normal(size=2000) for _ in range(5)]
    fold_preds = [rng.normal(size=2000) for _ in range(5)]
    p = block_bootstrap_p(fold_labels, fold_preds, B=200, seed=0)
    assert p > 0.10


def test_evaluate_gates_tradeable_lead():
    fold_ics = [0.08, 0.09, 0.08, 0.10, 0.09]
    linear_fold_ics = [0.01, 0.01, 0.02, 0.01, 0.01]
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.001)
    assert verdict == Verdict.TRADEABLE_LEAD


def test_evaluate_gates_linear_only_when_gbm_adds_nothing():
    fold_ics = [0.08, 0.09, 0.08, 0.10, 0.09]
    linear_fold_ics = [0.08, 0.09, 0.08, 0.10, 0.09]  # GBM == baseline exactly
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.001)
    assert verdict == Verdict.LINEAR_ONLY


def test_evaluate_gates_real_but_subthreshold():
    fold_ics = [0.01, 0.02, 0.01, 0.02, 0.01]  # real, below the 0.0726 floor
    linear_fold_ics = [0.001, 0.001, 0.001, 0.001, 0.001]
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.001)
    assert verdict == Verdict.REAL_BUT_SUBTHRESHOLD


def test_evaluate_gates_closed_when_not_significant():
    fold_ics = [0.001, -0.001, 0.001, -0.001, 0.001]
    linear_fold_ics = [0.0, 0.0, 0.0, 0.0, 0.0]
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.9)
    assert verdict == Verdict.CLOSED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bar_sequence_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.bar_sequence.stats'`

- [ ] **Step 3: Implement**

```python
# cq/research/bar_sequence/stats.py
"""Rank-IC, the block-bootstrap null, and the G1-G4 gates.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md §5-§6.
"""

from __future__ import annotations

import enum

import numpy as np
from scipy.stats import spearmanr

SIDAK_FAMILY_SIZE = 3
SIDAK_ALPHA = 1 - (1 - 0.05) ** (1 / SIDAK_FAMILY_SIZE)
COST_WALL_FLOOR = 0.0726
SIGN_CONSISTENCY_FRACTION = 4 / 5


class Verdict(enum.Enum):
    TRADEABLE_LEAD = "TRADEABLE-LEAD"
    REAL_BUT_SUBTHRESHOLD = "REAL-BUT-SUBTHRESHOLD"
    LINEAR_ONLY = "LINEAR-ONLY"
    CLOSED = "CLOSED"
    INVALID = "INVALID"  # set by the runner (Task 10) on a shuffle-label leakage hit,
    # never returned by evaluate_gates itself -- see Task 10 Step 3.


def rank_ic(pred: np.ndarray, label: np.ndarray) -> float:
    ic, _ = spearmanr(pred, label)
    return 0.0 if np.isnan(ic) else float(ic)


def block_length(n_test: int) -> int:
    """Politis-White-style cube-root heuristic, computed per fold from that
    fold's actual test sample size -- never a magic constant copied across
    folds or timeframes."""
    return max(1, round(n_test ** (1 / 3)))


def _block_permute(x: np.ndarray, block_len: int, rng: np.random.Generator) -> np.ndarray:
    n = len(x)
    n_blocks = -(-n // block_len)  # ceil division
    starts = rng.integers(0, n, size=n_blocks)
    pieces = [np.take(x, np.arange(s, s + block_len) % n, mode="wrap") for s in starts]
    return np.concatenate(pieces)[:n]


def block_bootstrap_p(
    fold_labels: list[np.ndarray], fold_preds: list[np.ndarray], B: int = 2000, seed: int = 0
) -> float:
    """Empirical p-value for the observed median-of-fold-IC statistic.

    Each fold's label sequence is independently block-permuted (predictions
    and the fold's own internal ordering are left alone), breaking only the
    pred-label coupling under test.
    """
    observed = np.median([rank_ic(p, l) for p, l in zip(fold_preds, fold_labels)])

    rng = np.random.default_rng(seed)
    null_medians = np.empty(B)
    for b in range(B):
        ics = []
        for label, pred in zip(fold_labels, fold_preds):
            shuffled_label = _block_permute(label, block_length(len(label)), rng)
            ics.append(rank_ic(pred, shuffled_label))
        null_medians[b] = np.median(ics)

    extreme = np.sum(np.abs(null_medians) >= abs(observed))
    return (extreme + 1) / (B + 1)


def evaluate_gates(
    gbm_fold_ics: list[float],
    linear_fold_ics: list[float],
    p_value: float,
    cost_floor: float = COST_WALL_FLOOR,
) -> Verdict:
    n_folds = len(gbm_fold_ics)
    g1 = p_value <= SIDAK_ALPHA
    sign = np.sign(gbm_fold_ics)
    dominant_sign = 1 if np.sum(sign > 0) >= np.sum(sign < 0) else -1
    g2 = np.mean(sign == dominant_sign) >= SIGN_CONSISTENCY_FRACTION
    g3 = np.mean(np.array(gbm_fold_ics) >= np.array(linear_fold_ics)) >= SIGN_CONSISTENCY_FRACTION
    g4 = np.median(np.abs(gbm_fold_ics)) >= cost_floor

    if not (g1 and g2):
        return Verdict.CLOSED
    if not g3:
        return Verdict.LINEAR_ONLY
    if not g4:
        return Verdict.REAL_BUT_SUBTHRESHOLD
    return Verdict.TRADEABLE_LEAD
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bar_sequence_stats.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add cq/research/bar_sequence/stats.py tests/test_bar_sequence_stats.py
git commit -m "feat(research): rank-IC, block-bootstrap null, and the G1-G4 gates"
```

---

### Task 9: `cq/research/bar_sequence/sanity.py` — shuffle-label leakage check

**Files:**
- Create: `cq/research/bar_sequence/sanity.py`
- Test: `tests/test_bar_sequence_sanity.py`

**Interfaces:**
- Consumes: `cq.research.bar_sequence.models.select_fold_models` shape of logic (reimplemented here against shuffled labels), `cq.research.bar_sequence.stats.rank_ic`.
- Produces: `shuffle_label_ic(returns, decision_ts_ms, fold, feature_set, seed) -> float`. Used by Task 10.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bar_sequence_sanity.py
import numpy as np

from cq.research.bar_sequence.folds import Fold
from cq.research.bar_sequence.sanity import shuffle_label_predictions
from cq.research.bar_sequence.stats import block_bootstrap_p, rank_ic


def test_shuffle_label_predictions_collapse_towards_zero_on_unrelated_data():
    fold = Fold(0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000)
    rng = np.random.default_rng(0)
    returns = rng.normal(scale=0.001, size=400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000

    pred, label = shuffle_label_predictions(returns, decision_ts_ms, fold, "sign", seed=0)
    ic = rank_ic(pred, label)
    assert abs(ic) < 0.3  # loose bound: a trained-on-noise model must not show strong OOS IC

    # The leakage check the runner actually applies (Task 10): the shuffle-trained
    # IC must not clear the same block-bootstrap null used for G1.
    p = block_bootstrap_p([label], [pred], B=200, seed=0)
    assert p > 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bar_sequence_sanity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.bar_sequence.sanity'`

- [ ] **Step 3: Implement**

```python
# cq/research/bar_sequence/sanity.py
"""Shuffle-label leakage check (protocol §7.1): retrain on the same features
with training labels randomly permuted, then evaluate on the REAL test-fold
labels. If this still shows non-trivial OOS IC, the feature construction is
leaking future information -- the model shouldn't be able to learn anything
from labels that carry no relationship to those features by construction.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from cq.research.bar_sequence.features import build_windows, standardize
from cq.research.bar_sequence.folds import Fold, assert_no_embargo_violation, fold_masks
from cq.research.bar_sequence.models import _features_for
from cq.research.bar_sequence.stats import rank_ic

_DEFAULT_LOOKBACK_N = 20


def shuffle_label_predictions(
    returns: np.ndarray,
    decision_ts_ms: np.ndarray,
    fold: Fold,
    feature_set: str,
    seed: int,
    lookback_n: int = _DEFAULT_LOOKBACK_N,
) -> tuple[np.ndarray, np.ndarray]:
    """(pred, label) on the REAL test fold, from a model trained on shuffled labels.

    Returns predictions rather than a bare IC so the caller (Task 10's runner)
    can run the same block-bootstrap null used for G1 against this pair,
    instead of eyeballing a magnitude threshold.
    """
    k, sign_window, ret_window, label = build_windows(returns, lookback_n)
    decision_ts_for_k = decision_ts_ms[k]
    train_mask, test_mask = fold_masks(decision_ts_for_k, fold)
    assert_no_embargo_violation(decision_ts_for_k[train_mask], fold)

    ret_z = standardize(ret_window, train_mask)
    X = _features_for(feature_set, sign_window, ret_z)
    y_true_train = (label[train_mask] > 0).astype(int)

    rng = np.random.default_rng(seed)
    y_shuffled_train = rng.permutation(y_true_train)

    model = HistGradientBoostingClassifier(
        max_depth=3, min_samples_leaf=500, learning_rate=0.05, max_iter=200, n_iter_no_change=30
    )
    model.fit(X[train_mask], y_shuffled_train)
    pred = model.predict_proba(X[test_mask])[:, 1]
    return pred, label[test_mask]
```

- [ ] **Step 4: Expose `_features_for` for reuse**

`_features_for` in `cq/research/bar_sequence/models.py` (Task 7) is currently name-mangled as
private. Rename it to `features_for` (drop the leading underscore) in `models.py` and update
its one call site inside `select_fold_models`, so `sanity.py` can import it without reaching
into another module's private namespace. Update the import in `sanity.py` to
`from cq.research.bar_sequence.models import features_for` and the call site accordingly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_bar_sequence_sanity.py tests/test_bar_sequence_models.py -v`
Expected: PASS (all tests in both files — this checks the rename in Step 4 didn't break Task 7's tests)

- [ ] **Step 6: Commit**

```bash
git add cq/research/bar_sequence/sanity.py cq/research/bar_sequence/models.py tests/test_bar_sequence_sanity.py
git commit -m "feat(research): shuffle-label leakage sanity check"
```

---

### Task 10: `cq/research/bar_sequence/runner.py` — orchestration and JSON report

**Files:**
- Create: `cq/research/bar_sequence/runner.py`
- Test: `tests/test_bar_sequence_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 2-9.
- Produces: `run_study(store) -> dict` (the full JSON-serializable report). Used by Task 11 (CLI).

- [ ] **Step 1: Write the failing test**

This test uses a small synthetic in-memory `Store` (not the real multi-year history) so it
runs fast — it verifies the orchestration and report shape, not a real research conclusion.

```python
# tests/test_bar_sequence_runner.py
import numpy as np
import pytest

from cq.data.store import Store
from cq.research.bar_sequence.stats import Verdict


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def test_run_study_shape_on_synthetic_data(store, monkeypatch):
    # Patch the frozen fingerprint/count constants to match a small synthetic
    # dataset -- this test is about orchestration correctness, not about
    # reproducing the real multi-year fingerprint (that is Task 3 Step 5's job).
    import cq.research.bar_sequence.data as data_mod

    rng = np.random.default_rng(0)
    n_bars = 2000
    closes = 1.0 + np.cumsum(rng.normal(scale=0.001, size=n_bars))
    rows = []
    for i, c in enumerate(closes):
        ts = data_mod.explore_window()[0] + i * 300_000
        rows.append(("DOGE-USDT", ts, c, c, c, c, 10.0, 10.0 * c))
    store.upsert_ohlcv(rows)

    frame = store.load_ohlcv("DOGE-USDT", "5m")
    fingerprint = data_mod.data_fingerprint(frame)
    monkeypatch.setattr(data_mod, "EXPECTED_RAW_FINGERPRINT", fingerprint)
    monkeypatch.setattr(data_mod, "EXPECTED_RAW_BAR_COUNT", len(frame))
    monkeypatch.setattr(data_mod, "EXPECTED_DEGENERATE_DROP_COUNT", 0)

    import cq.research.bar_sequence.folds as folds_mod

    monkeypatch.setattr(
        folds_mod,
        "FOLDS",
        (
            folds_mod.Fold(
                data_mod.explore_window()[0],
                data_mod.explore_window()[0] + 800 * 300_000,
                data_mod.explore_window()[0] + 800 * 300_000 + 86_400_000,
                data_mod.explore_window()[0] + 1400 * 300_000,
            ),
            folds_mod.Fold(
                data_mod.explore_window()[0],
                data_mod.explore_window()[0] + 1400 * 300_000,
                data_mod.explore_window()[0] + 1400 * 300_000 + 86_400_000,
                data_mod.explore_window()[0] + 1900 * 300_000,
            ),
        ),
    )

    from cq.research.bar_sequence.runner import run_study

    report = run_study(store)

    assert report["dropped_degenerate_bars"] == 0
    assert set(report["feature_sets"].keys()) == {"sign", "ret", "both"}
    for name, result in report["feature_sets"].items():
        assert result["verdict"] in {v.value for v in Verdict}
        assert len(result["fold_gbm_ic"]) == 2
        assert len(result["fold_linear_ic"]) == 2
        assert "p_value" in result
        assert "shuffle_label_ic" in result
        assert "shuffle_label_p_value" in result


def test_run_study_marks_invalid_on_a_leakage_hit(store, monkeypatch):
    import cq.research.bar_sequence.data as data_mod
    import cq.research.bar_sequence.folds as folds_mod
    import cq.research.bar_sequence.runner as runner_mod

    rng = np.random.default_rng(0)
    n_bars = 2000
    closes = 1.0 + np.cumsum(rng.normal(scale=0.001, size=n_bars))
    rows = []
    for i, c in enumerate(closes):
        ts = data_mod.explore_window()[0] + i * 300_000
        rows.append(("DOGE-USDT", ts, c, c, c, c, 10.0, 10.0 * c))
    store.upsert_ohlcv(rows)

    frame = store.load_ohlcv("DOGE-USDT", "5m")
    monkeypatch.setattr(data_mod, "EXPECTED_RAW_FINGERPRINT", data_mod.data_fingerprint(frame))
    monkeypatch.setattr(data_mod, "EXPECTED_RAW_BAR_COUNT", len(frame))
    monkeypatch.setattr(data_mod, "EXPECTED_DEGENERATE_DROP_COUNT", 0)
    monkeypatch.setattr(
        folds_mod,
        "FOLDS",
        (
            folds_mod.Fold(
                data_mod.explore_window()[0],
                data_mod.explore_window()[0] + 800 * 300_000,
                data_mod.explore_window()[0] + 800 * 300_000 + 86_400_000,
                data_mod.explore_window()[0] + 1400 * 300_000,
            ),
        ),
    )

    # Force the leakage check to report a suspiciously perfect (pred, label)
    # pair regardless of feature_set -- this must flip every verdict to
    # INVALID, overriding whatever G1-G4 would otherwise have said.
    def fake_shuffle_predictions(returns, decision_ts_ms, fold, feature_set, seed):
        label = np.linspace(-1, 1, 500)
        return label.copy(), label

    monkeypatch.setattr(runner_mod, "shuffle_label_predictions", fake_shuffle_predictions)

    report = runner_mod.run_study(store)

    for result in report["feature_sets"].values():
        assert result["verdict"] == Verdict.INVALID.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bar_sequence_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cq.research.bar_sequence.runner'`

- [ ] **Step 3: Implement**

```python
# cq/research/bar_sequence/runner.py
"""Orchestrates the full bar-sequence-GBM study end to end and produces the
JSON-serializable report described in
docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md.
"""

from __future__ import annotations

from cq.data.store import Store
from cq.research.bar_sequence.data import load_explore_bars, log_returns
from cq.research.bar_sequence.folds import FOLDS
from cq.research.bar_sequence.models import FEATURE_SETS, select_fold_models
from cq.research.bar_sequence.sanity import shuffle_label_predictions
from cq.research.bar_sequence.stats import Verdict, block_bootstrap_p, evaluate_gates, rank_ic

LEAKAGE_ALPHA = 0.05  # not Sidak-corrected: this is a sanity check, not a hypothesis test


def run_study(store: Store) -> dict:
    frame, dropped = load_explore_bars(store)
    returns = log_returns(frame)
    decision_ts_ms = frame.index.astype("int64").to_numpy()[1:] // 1_000_000

    feature_set_results = {}

    for feature_set in FEATURE_SETS:
        fold_gbm_ic = []
        fold_linear_ic = []
        fold_label_arrays = []
        fold_gbm_pred_arrays = []

        for fold in FOLDS:
            fit = select_fold_models(returns, decision_ts_ms, fold, feature_set)
            fold_gbm_ic.append(rank_ic(fit.gbm_pred, fit.test_label))
            fold_linear_ic.append(rank_ic(fit.logistic_pred, fit.test_label))
            fold_label_arrays.append(fit.test_label)
            fold_gbm_pred_arrays.append(fit.gbm_pred)

        p_value = block_bootstrap_p(fold_label_arrays, fold_gbm_pred_arrays)
        verdict = evaluate_gates(fold_gbm_ic, fold_linear_ic, p_value)

        # Shuffle-label leakage check (protocol §7.1): train on shuffled labels,
        # then test the resulting (pred, label) pair against the SAME
        # block-bootstrap null used for G1. A hit here means the feature
        # construction leaked future information -- it overrides G1-G4.
        shuffle_pred, shuffle_label = shuffle_label_predictions(
            returns, decision_ts_ms, FOLDS[0], feature_set, seed=0
        )
        shuffle_ic = rank_ic(shuffle_pred, shuffle_label)
        shuffle_p_value = block_bootstrap_p([shuffle_label], [shuffle_pred])
        if shuffle_p_value <= LEAKAGE_ALPHA:
            verdict = Verdict.INVALID

        feature_set_results[feature_set] = {
            "fold_gbm_ic": fold_gbm_ic,
            "fold_linear_ic": fold_linear_ic,
            "p_value": p_value,
            "shuffle_label_ic": shuffle_ic,
            "shuffle_label_p_value": shuffle_p_value,
            "verdict": verdict.value,
        }

    return {
        "study_tag": "doge-bar-sequence-gbm-v1",
        "dropped_degenerate_bars": dropped,
        "feature_sets": feature_set_results,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bar_sequence_runner.py -v`
Expected: PASS. This exercises the full pipeline (3 feature sets × 2 folds × grid search), so
allow up to a minute.

- [ ] **Step 5: Commit**

```bash
git add cq/research/bar_sequence/runner.py tests/test_bar_sequence_runner.py
git commit -m "feat(research): end-to-end bar-sequence-GBM study orchestration"
```

---

### Task 11: CLI wiring — `cq research bar-sequence-gbm run`

**Files:**
- Create: `cq/research/commands.py`
- Modify: `cq/cli.py`
- Modify: `.gitignore`
- Test: `tests/test_research_commands.py`

**Interfaces:**
- Consumes: `cq.research.bar_sequence.runner.run_study`.
- Produces: the `cq research bar-sequence-gbm run` subcommand, writing
  `reports/research/doge_bar_sequence_gbm.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_commands.py
import json

from cq.cli import build_parser


def test_research_bar_sequence_gbm_run_is_registered():
    parser = build_parser()
    args = parser.parse_args(["research", "bar-sequence-gbm", "run", "--out", "/tmp/does-not-matter.json"])
    assert args.handler is not None


def test_run_writes_the_report_json(tmp_path, monkeypatch):
    from cq.research import commands

    monkeypatch.setattr(
        commands,
        "run_study",
        lambda store: {"study_tag": "doge-bar-sequence-gbm-v1", "feature_sets": {}},
    )
    out_path = tmp_path / "report.json"

    from cq.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["research", "bar-sequence-gbm", "run", "--out", str(out_path), "--db", str(tmp_path / "cq.db")]
    )
    exit_code = args.handler(args)

    assert exit_code == 0
    written = json.loads(out_path.read_text())
    assert written["study_tag"] == "doge-bar-sequence-gbm-v1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research_commands.py -v`
Expected: FAIL — `research` is not a registered subcommand yet.

- [ ] **Step 3: Implement `cq/research/commands.py`**

```python
# cq/research/commands.py
"""CLI wiring for research studies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.bar_sequence.runner import run_study

DEFAULT_OUT_PATH = Path("reports/research/doge_bar_sequence_gbm.json")


def _run_bar_sequence_gbm(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    out_path = Path(args.out) if args.out else DEFAULT_OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Store(db_path) as store:
        report = run_study(store)

    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"wrote {out_path}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    bar_sequence_gbm = subparsers.add_parser(
        "bar-sequence-gbm", help="doge-bar-sequence-gbm-v1: bar-return-sequence GBM study"
    )
    bar_sequence_sub = bar_sequence_gbm.add_subparsers(dest="bar_sequence_command", required=True)

    run_parser = bar_sequence_sub.add_parser("run", help="run the frozen protocol end to end")
    run_parser.add_argument("--out", help="output JSON path (default: reports/research/doge_bar_sequence_gbm.json)")
    run_parser.add_argument("--db", help="sqlite db path (default: data/cq.db)")
    run_parser.set_defaults(handler=_run_bar_sequence_gbm)
```

- [ ] **Step 4: Wire into `cq/cli.py`**

In `cq/cli.py`, add a new subparser group next to the existing `data`/`backtest`/`paper` ones:

```python
    research = subparsers.add_parser("research", help="run pre-registered research studies")
    research_sub = research.add_subparsers(dest="research_study", required=True)
    _register_research_commands(research_sub)
```

And a matching registration function alongside `_register_paper_commands`:

```python
def _register_research_commands(subparsers: argparse._SubParsersAction) -> None:
    from cq.research import commands

    commands.register(subparsers)
```

- [ ] **Step 5: Whitelist the new report path in `.gitignore`**

In `.gitignore`, under the existing `reports/research/*` block (which has several
`!reports/research/<name>.json` whitelist lines for now-deleted studies), add:

```
!reports/research/doge_bar_sequence_gbm.json
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_research_commands.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add cq/research/commands.py cq/cli.py .gitignore tests/test_research_commands.py
git commit -m "feat(research): wire bar-sequence-gbm into the cq CLI"
```

---

### Task 12: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test suite**

Run: `pytest -v`
Expected: All tests pass, including every test added in Tasks 2-11 and the pre-existing suite
(no regressions in `cq/data`, `cq/backtest`, `cq/engine`, `cq/live`).

- [ ] **Step 2: Run the real-data fingerprint check one more time**

Run:
```bash
python3 -c "
from cq.data.store import Store
from cq.research.bar_sequence.data import load_explore_bars
with Store() as store:
    frame, dropped = load_explore_bars(store)
    print('bars:', len(frame), 'dropped:', dropped)
"
```
Expected: `bars: 463640 dropped: 520` — unchanged from Task 3 Step 5. If this now differs, the
underlying `data/cq.db` changed between when this plan was written and now (e.g. a backfill
ran); stop and re-freeze the protocol's numbers rather than proceeding on stale ones.

- [ ] **Step 3: Lint and type-check**

Run: `ruff check cq/research tests/test_research_split.py tests/test_bar_sequence_*.py tests/test_research_commands.py`
Run: `pyright cq/research`
Expected: no errors. Fix anything flagged before considering this plan done.

---

## After this plan

This plan only builds the measurement apparatus and proves it runs end to end (Task 10's test
uses synthetic data; Task 12 only re-checks the fingerprint, not the actual verdict). It
deliberately stops short of:

- **Running the study for real** (`cq research bar-sequence-gbm run`) against the full
  2021-2025 explore window and reading the resulting verdict.
- **Writing `BAR_SEQUENCE_GBM_RESULTS_2026-07-31.md`** — the results doc, following the same
  repo convention as e.g. `DOLLAR_CLOCK_RESULTS_2026-07-30.md`.

Both belong to a separate step, after this plan's code has been reviewed — running the
protocol and writing up its conclusion is the actual research act, and per the protocol's own
pre-registration discipline (§0), that must happen *after* the apparatus is frozen and
reviewed, not folded into the same commit that built it.
