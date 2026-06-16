"""Out-of-sample splitting utilities for chronological data.

Provides train/test splits that respect time-ordering — no shuffling,
no look-ahead bias. Supports simple chronological hold-out and
walk-forward expanding-window cross-validation.
"""

from typing import Union

import pandas as pd


def split_train_test(
    df: pd.DataFrame,
    test_frac: float = 0.2,
    method: str = "simple",
    n_splits: int = 5,
) -> Union[tuple[pd.DataFrame, pd.DataFrame], list[tuple[pd.DataFrame, pd.DataFrame]]]:
    """Split a chronological DataFrame into train and test sets.

    Args:
        df: Input DataFrame with a sorted DatetimeIndex.
        test_frac: Fraction of data to reserve for testing (simple mode only).
        method: Splitting strategy — ``"simple"`` or ``"walk_forward"``.
        n_splits: Number of folds for walk-forward mode.

    Returns:
        For ``method="simple"``: a single ``(train_df, test_df)`` tuple.
        For ``method="walk_forward"``: a list of ``(train_df, test_df)`` tuples,
        one per fold, with expanding training windows and non-overlapping test
        windows.

    Raises:
        ValueError: If ``method`` is not ``"simple"`` or ``"walk_forward"``,
            or if the DataFrame is too short for the requested split.
    """
    if method not in ("simple", "walk_forward"):
        raise ValueError(f"method must be 'simple' or 'walk_forward', got {method!r}")

    n = len(df)
    if n < 2:
        raise ValueError(f"DataFrame must have at least 2 rows, got {n}")

    if method == "simple":
        split_idx = int(n * (1 - test_frac))
        if split_idx < 1 or split_idx >= n:
            raise ValueError(
                f"test_frac={test_frac} produces invalid split index {split_idx} for n={n} rows"
            )
        train = df.iloc[:split_idx].copy()
        test = df.iloc[split_idx:].copy()
        return train, test

    # walk_forward: expanding train + non-overlapping test
    n_chunks = n_splits + 1
    chunk_size = n // n_chunks
    if chunk_size < 1:
        raise ValueError(
            f"n_splits={n_splits} too large for n={n} rows (chunk_size would be {chunk_size})"
        )

    folds: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    for i in range(n_splits):
        train_end = (i + 1) * chunk_size
        test_end = min((i + 2) * chunk_size, n)
        # Last fold: ensure test uses all remaining rows
        if i == n_splits - 1:
            test_end = n
        train = df.iloc[:train_end].copy()
        test = df.iloc[train_end:test_end].copy()
        folds.append((train, test))

    return folds
