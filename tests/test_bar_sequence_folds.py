from datetime import UTC, datetime

import numpy as np
import pytest

from cq.research.bar_sequence.folds import FOLDS, Fold, assert_no_embargo_violation, fold_masks


def _ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


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


@pytest.mark.parametrize(
    "windows",
    [
        (0, 100, 50, 150),  # test starts inside the train window
        (0, 100, 90, 95),  # test window entirely inside the train window
        (100, 100, 200, 300),  # empty train window
        (0, 100, 200, 200),  # empty test window
        (0, 100, 90, 80),  # test window runs backwards
        (200, 100, 300, 400),  # train window runs backwards
    ],
)
def test_fold_rejects_windows_that_are_not_a_forward_split(windows):
    # fold_masks selects purely by timestamp range, so an out-of-order fold
    # silently marks the same decision points as both train and test --
    # and assert_no_embargo_violation's predicate is structurally empty in
    # exactly that case. The invariant makes it a construction-time error.
    with pytest.raises(ValueError):
        Fold(*windows)


def test_fold_accepts_a_split_with_no_embargo_gap():
    # train_end == test_start is legal: the gap is optional, the ordering is not.
    fold = Fold(0, 100, 100, 200)
    assert fold.train_end_ms == fold.test_start_ms


def test_frozen_folds_satisfy_the_forward_split_invariant():
    for fold in FOLDS:
        assert fold.train_start_ms < fold.train_end_ms <= fold.test_start_ms < fold.test_end_ms


def test_assert_no_embargo_violation_catches_a_leaking_train_set():
    fold = FOLDS[0]
    leaking_ts = np.array([fold.train_end_ms])  # inside the embargo gap
    with pytest.raises(AssertionError):
        assert_no_embargo_violation(leaking_ts, fold)
