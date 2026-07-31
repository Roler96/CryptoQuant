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
    if N < 1 or N > M0 - 1:
        raise ValueError(
            f"N={N} leaves no valid decision points for {M0} returns "
            f"(need N <= len(returns) - 1)"
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
