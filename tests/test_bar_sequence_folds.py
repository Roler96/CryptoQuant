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
            fold.train_start_ms,  # first train ms, included
            fold.train_end_ms - 1,  # last train ms, included
            fold.train_end_ms,  # inside the embargo gap, excluded from both
            fold.test_start_ms,  # first test ms, included
            fold.test_end_ms - 1,  # last test ms, included
            fold.test_end_ms,  # exclusive end, excluded
        ]
    )
    train_mask, test_mask = fold_masks(decision_ts, fold)
    np.testing.assert_array_equal(train_mask, [True, True, False, False, False, False])
    np.testing.assert_array_equal(test_mask, [False, False, False, True, True, False])


def test_assert_no_embargo_violation_catches_a_leaking_train_set():
    fold = FOLDS[0]
    leaking_ts = np.array([fold.train_end_ms])  # inside the embargo gap
    with pytest.raises(AssertionError):
        assert_no_embargo_violation(leaking_ts, fold)
