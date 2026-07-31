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
