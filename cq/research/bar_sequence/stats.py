"""Rank-IC, the block-bootstrap null, and the G1-G4 gates.

See docs/research/doge-5m/BAR_SEQUENCE_GBM_PROTOCOL_2026-07-31.md §5-§6.
"""

from __future__ import annotations

import enum

import numpy as np
from scipy.stats import spearmanr

SIDAK_FAMILY_SIZE = 3
SIDAK_ALPHA = 1 - (1 - 0.05) ** (1 / SIDAK_FAMILY_SIZE)
COST_WALL_FLOOR = 0.0726
SIGN_CONSISTENCY_FRACTION = 4 / 5


class Verdict(enum.Enum):
    TRADEABLE_LEAD = "TRADEABLE-LEAD"
    REAL_BUT_SUBTHRESHOLD = "REAL-BUT-SUBTHRESHOLD"
    LINEAR_ONLY = "LINEAR-ONLY"
    CLOSED = "CLOSED"
    INVALID = "INVALID"  # set by the runner (Task 11) on a shuffle-label leakage hit,
    # never returned by evaluate_gates itself -- see Task 11 Step 3.


def rank_ic(pred: np.ndarray, label: np.ndarray) -> float:
    ic = float(spearmanr(pred, label).statistic)  # type: ignore[attr-defined]
    return 0.0 if np.isnan(ic) else ic


def block_length(n_test: int) -> int:
    """Politis-White-style cube-root heuristic, computed per fold from that
    fold's actual test sample size -- never a magic constant copied across
    folds or timeframes."""
    return max(1, round(n_test ** (1 / 3)))


def _block_permute(x: np.ndarray, block_len: int, rng: np.random.Generator) -> np.ndarray:
    n = len(x)
    n_blocks = -(-n // block_len)  # ceil division
    starts = rng.integers(0, n, size=n_blocks)
    pieces = [np.take(x, np.arange(s, s + block_len) % n, mode="wrap") for s in starts]
    return np.concatenate(pieces)[:n]


def block_bootstrap_p(
    fold_labels: list[np.ndarray], fold_preds: list[np.ndarray], B: int = 2000, seed: int = 0
) -> float:
    """Empirical p-value for the observed median-of-fold-IC statistic.

    Each fold's label sequence is independently block-permuted (predictions
    and the fold's own internal ordering are left alone), breaking only the
    pred-label coupling under test.
    """
    observed = np.median(
        [rank_ic(p, lbl) for p, lbl in zip(fold_preds, fold_labels, strict=True)]
    )

    rng = np.random.default_rng(seed)
    null_medians = np.empty(B)
    for b in range(B):
        ics = []
        for label, pred in zip(fold_labels, fold_preds, strict=True):
            shuffled_label = _block_permute(label, block_length(len(label)), rng)
            ics.append(rank_ic(pred, shuffled_label))
        null_medians[b] = np.median(ics)

    extreme = np.sum(np.abs(null_medians) >= abs(observed))
    return (extreme + 1) / (B + 1)


def evaluate_gates(
    gbm_fold_ics: list[float],
    linear_fold_ics: list[float],
    p_value: float,
    cost_floor: float = COST_WALL_FLOOR,
) -> Verdict:
    g1 = p_value <= SIDAK_ALPHA
    sign = np.sign(gbm_fold_ics)
    dominant_sign = 1 if np.sum(sign > 0) >= np.sum(sign < 0) else -1
    g2 = np.mean(sign == dominant_sign) >= SIGN_CONSISTENCY_FRACTION
    g3 = np.mean(np.array(gbm_fold_ics) > np.array(linear_fold_ics)) >= SIGN_CONSISTENCY_FRACTION
    g4 = np.median(np.abs(gbm_fold_ics)) >= cost_floor

    if not (g1 and g2):
        return Verdict.CLOSED
    if not g3:
        return Verdict.LINEAR_ONLY
    if not g4:
        return Verdict.REAL_BUT_SUBTHRESHOLD
    return Verdict.TRADEABLE_LEAD
