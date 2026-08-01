"""Orchestrate the full bar-sequence-GBM study end-to-end.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md for the
expected protocol and report schema.
"""

from __future__ import annotations

from cq.data.store import Store
from cq.research.bar_sequence.data import load_explore_bars, log_returns
from cq.research.bar_sequence.folds import FOLDS
from cq.research.bar_sequence.models import FEATURE_SETS, select_fold_models
from cq.research.bar_sequence.sanity import shuffle_label_predictions
from cq.research.bar_sequence.stats import Verdict, block_bootstrap_p, evaluate_gates, rank_ic

LEAKAGE_ALPHA = 0.05  # Not Sidak-adjusted: a targeted sanity check, not a hypothesis test.
STUDY_TAG = "doge-bar-sequence-gbm-v1"


def run_study(store: Store) -> dict:
    """Run all feature sets across all frozen folds and produce a JSON-ready report."""
    frame, dropped_degenerate_bars = load_explore_bars(store)
    returns = log_returns(frame)
    decision_ts_ms = frame.index.astype("int64").to_numpy() // 1_000_000

    feature_set_results: dict[str, dict[str, object]] = {}

    for feature_set in FEATURE_SETS:
        fold_gbm_ic: list[float] = []
        fold_linear_ic: list[float] = []
        fold_label_arrays: list = []
        fold_gbm_pred_arrays: list = []

        for fold in FOLDS:
            fit = select_fold_models(returns, decision_ts_ms, fold, feature_set)
            fold_gbm_ic.append(rank_ic(fit.gbm_pred, fit.test_label))
            fold_linear_ic.append(rank_ic(fit.logistic_pred, fit.test_label))
            fold_label_arrays.append(fit.test_label)
            fold_gbm_pred_arrays.append(fit.gbm_pred)

        p_value = block_bootstrap_p(fold_label_arrays, fold_gbm_pred_arrays)
        verdict = evaluate_gates(fold_gbm_ic, fold_linear_ic, p_value)

        # Shuffle-label leakage check (protocol §7.1): train on shuffled labels for one
        # representative fold to detect obvious leakage in feature construction.
        # A hit here flips the verdict to INVALID even if gating would otherwise pass.
        shuffle_pred, shuffle_label = shuffle_label_predictions(
            returns,
            decision_ts_ms,
            FOLDS[0],
            feature_set,
            seed=0,
            lookback_n=20,
        )
        shuffle_label_ic = rank_ic(shuffle_pred, shuffle_label)
        shuffle_label_p_value = block_bootstrap_p([shuffle_label], [shuffle_pred], seed=0)
        if shuffle_label_p_value <= LEAKAGE_ALPHA:
            verdict = Verdict.INVALID

        feature_set_results[feature_set] = {
            "fold_gbm_ic": fold_gbm_ic,
            "fold_linear_ic": fold_linear_ic,
            "p_value": p_value,
            "shuffle_label_ic": shuffle_label_ic,
            "shuffle_label_p_value": shuffle_label_p_value,
            "verdict": verdict.value,
        }

    return {
        "study_tag": STUDY_TAG,
        "dropped_degenerate_bars": dropped_degenerate_bars,
        "feature_sets": feature_set_results,
    }
