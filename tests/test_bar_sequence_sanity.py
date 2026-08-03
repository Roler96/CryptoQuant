"""Protocol §7.1 shuffle-label leakage checks.

If this test path is executed in an environment without sklearn, it is skipped.
"""

from unittest.mock import patch

import numpy as np
import pytest

pytest.importorskip("sklearn", reason="sklearn is required for shuffle-label leakage check")

from sklearn.ensemble import HistGradientBoostingClassifier

from cq.research.bar_sequence.folds import Fold
from cq.research.bar_sequence.sanity import shuffle_label_predictions
from cq.research.bar_sequence.stats import block_bootstrap_p, rank_ic


def _fold_and_returns(seed=0, n=400):
    fold = Fold(
        0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000
    )
    rng = np.random.default_rng(seed)
    returns = rng.normal(scale=0.001, size=n)
    decision_ts_ms = fold.train_start_ms + np.arange(1, n + 1) * 300_000
    return fold, returns, decision_ts_ms


def test_shuffle_label_predictions_collapse_towards_zero_on_unrelated_data():
    fold, returns, decision_ts_ms = _fold_and_returns(seed=0)

    pred, label = shuffle_label_predictions(returns, decision_ts_ms, fold, "sign", seed=0)
    ic = rank_ic(pred, label)

    assert abs(ic) < 0.3


def test_shuffle_label_predictions_uses_block_bootstrap_null():
    fold, returns, decision_ts_ms = _fold_and_returns(seed=1)

    pred, label = shuffle_label_predictions(returns, decision_ts_ms, fold, "both", seed=123)
    p = block_bootstrap_p([label], [pred], B=200, seed=0)

    assert p > 0.05


class _StopAfterInit(Exception):
    pass


def test_shuffle_label_predictions_disables_the_random_validation_split():
    """Root cause (2026-08-03): with validation_fraction left at its sklearn
    default, HistGradientBoostingClassifier's early-stopping split draws from
    the unseeded global numpy RNG, so this "reproducible" seed=0 check
    produced different shuffle_label_ic/p values across separate process
    launches on the real study data. validation_fraction=None (matching
    models.py's existing convention) makes early stopping use training loss
    instead of a random held-out split, removing that dependency."""
    fold, returns, decision_ts_ms = _fold_and_returns(seed=0)

    with patch.object(HistGradientBoostingClassifier, "__init__", autospec=True) as mock_init:
        mock_init.side_effect = _StopAfterInit
        with pytest.raises(_StopAfterInit):
            shuffle_label_predictions(returns, decision_ts_ms, fold, "sign", seed=0)

    assert mock_init.call_args.kwargs.get("validation_fraction", "MISSING") is None
