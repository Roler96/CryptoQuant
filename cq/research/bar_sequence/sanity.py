"""Shuffle-label leakage check (protocol §7.1).

Retrain models on shuffled labels to test for feature-label leakage:
construct features from each decision point exactly as the normal training
path, but randomize the training labels before fitting. On unrelated data,
model OOS IC should be near zero and block-bootstrap null should not reject.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from cq.research.bar_sequence.features import build_windows, standardize
from cq.research.bar_sequence.folds import Fold, assert_no_embargo_violation, fold_masks
from cq.research.bar_sequence.models import features_for

DEFAULT_LOOKBACK_N = 20


def shuffle_label_predictions(
    returns: np.ndarray,
    decision_ts_ms: np.ndarray,
    fold: Fold,
    feature_set: str,
    seed: int,
    lookback_n: int = DEFAULT_LOOKBACK_N,
) -> tuple[np.ndarray, np.ndarray]:
    """Train a model on shuffled labels and return (pred, label) on real test fold.

    Returns:
        pred: probability predictions for the test fold
        label: real test fold labels (for the same decision points)
    """
    k, sign_window, ret_window, label = build_windows(returns, lookback_n)
    decision_ts_for_k = decision_ts_ms[k]

    train_mask, test_mask = fold_masks(decision_ts_for_k, fold)
    assert_no_embargo_violation(decision_ts_for_k[train_mask], fold)

    ret_z = standardize(ret_window, train_mask)
    X = features_for(feature_set, sign_window, ret_z)

    y_true_train = (label[train_mask] > 0).astype(int)
    rng = np.random.default_rng(seed)
    y_train = rng.permutation(y_true_train)

    model = HistGradientBoostingClassifier(
        max_depth=3,
        min_samples_leaf=500,
        learning_rate=0.05,
        max_iter=200,
        n_iter_no_change=30,
        # Matches models.py's convention: without this, early stopping falls
        # back to its default internal train/validation split, which draws
        # from the unseeded global numpy RNG (random_state=None) -- making
        # this "reproducible" seed=0 check non-reproducible across process
        # launches. Root-caused 2026-08-03: identical seed=0 inputs produced
        # different shuffle_label_ic/p across separate process runs until
        # this was added; verified bit-identical afterward.
        validation_fraction=None,  # type: ignore[arg-type]
    )
    model.fit(X[train_mask], y_train)

    pred = model.predict_proba(X[test_mask])[:, 1]
    return pred, label[test_mask]
