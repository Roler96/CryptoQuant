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
