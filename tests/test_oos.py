"""Tests for out-of-sample splitting utilities."""
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false, reportIndexIssue=false

import numpy as np
import pandas as pd
import pytest

from cryptoquant.data.oos import split_train_test


def _make_df(n=200, start="2024-01-01"):
    """Generate a chronological DataFrame."""
    dates = pd.date_range(start, periods=n, freq="1h")
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
    close = np.linspace(100, 100 + n * 0.5, n)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestSimpleSplit:
    def test_80_20_sizes(self):
        df = _make_df(100)
        train, test = split_train_test(df, test_frac=0.2, method="simple")
        assert len(train) == 80
        assert len(test) == 20
        assert len(train) + len(test) == len(df)

    def test_no_overlap(self):
        df = _make_df(100)
        train, test = split_train_test(df, test_frac=0.2, method="simple")
        overlap = train.index.intersection(test.index)
        assert len(overlap) == 0

    def test_chronological_order(self):
        df = _make_df(100)
        train, test = split_train_test(df, test_frac=0.2, method="simple")
        assert train.index[-1] < test.index[0]

    def test_index_preserved(self):
        df = _make_df(100)
        train, test = split_train_test(df, test_frac=0.2, method="simple")
        assert (train.index == df.index[:80]).all()
        assert (test.index == df.index[80:]).all()

    def test_invalid_method_raises(self):
        df = _make_df(100)
        with pytest.raises(ValueError, match="method must be"):
            split_train_test(df, method="random")

    def test_too_short_raises(self):
        df = _make_df(1)
        with pytest.raises(ValueError, match="at least 2 rows"):
            split_train_test(df, test_frac=0.2, method="simple")

    def test_extreme_test_frac_raises(self):
        df = _make_df(10)
        with pytest.raises(ValueError, match="invalid split index"):
            split_train_test(df, test_frac=0.95, method="simple")


class TestWalkForwardSplit:
    def test_n_splits_folds(self):
        df = _make_df(120)
        folds = split_train_test(df, method="walk_forward", n_splits=5)
        assert isinstance(folds, list)
        assert len(folds) == 5

    def test_no_overlap_within_fold(self):
        df = _make_df(120)
        folds = split_train_test(df, method="walk_forward", n_splits=5)
        for train, test in folds:
            overlap = train.index.intersection(test.index)
            assert len(overlap) == 0

    def test_no_overlap_across_test_sets(self):
        df = _make_df(120)
        folds = split_train_test(df, method="walk_forward", n_splits=5)
        all_test_indices = []
        for _, test in folds:
            all_test_indices.extend(test.index.tolist())
        # Each row should appear in at most one test set
        assert len(all_test_indices) == len(set(all_test_indices))

    def test_expanding_train_window(self):
        df = _make_df(120)
        folds = split_train_test(df, method="walk_forward", n_splits=5)
        train_sizes = [len(train) for train, _ in folds]
        assert train_sizes == sorted(train_sizes)
        assert len(set(train_sizes)) == len(train_sizes)  # strictly increasing

    def test_index_preserved(self):
        df = _make_df(120)
        folds = split_train_test(df, method="walk_forward", n_splits=5)
        for train, test in folds:
            combined_index = train.index.append(test.index)
            assert combined_index.is_monotonic_increasing
            # All indices must exist in the original DataFrame
            assert combined_index.isin(df.index).all()

    def test_last_fold_uses_all_remaining_rows(self):
        df = _make_df(100)
        folds = split_train_test(df, method="walk_forward", n_splits=5)
        _, last_test = folds[-1]
        # The last test set should end at the final index of df
        assert last_test.index[-1] == df.index[-1]

    def test_too_many_splits_raises(self):
        df = _make_df(5)
        with pytest.raises(ValueError, match="too large"):
            split_train_test(df, method="walk_forward", n_splits=5)
