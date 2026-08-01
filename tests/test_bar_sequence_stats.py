import numpy as np
import pytest

from cq.research.bar_sequence.stats import (
    SIDAK_ALPHA,
    Verdict,
    block_bootstrap_p,
    block_length,
    evaluate_gates,
    rank_ic,
)


def test_rank_ic_matches_spearman_on_a_known_case():
    pred = np.array([0.1, 0.2, 0.3, 0.4])
    label = np.array([-1.0, -2.0, -3.0, -4.0])  # perfectly anti-monotonic
    assert rank_ic(pred, label) == pytest.approx(-1.0)


def test_block_length_uses_cube_root_heuristic():
    assert block_length(1000) == round(1000 ** (1 / 3))
    assert block_length(1) == 1  # never degenerate to zero


def test_sidak_alpha_for_family_of_three():
    assert SIDAK_ALPHA == pytest.approx(1 - (1 - 0.05) ** (1 / 3))


def test_block_bootstrap_p_is_small_for_a_strong_real_relationship():
    rng = np.random.default_rng(0)
    fold_labels = [rng.normal(size=2000) for _ in range(5)]
    # pred is a noisy but strong copy of label -- true signal, not noise.
    fold_preds = [lbl + rng.normal(scale=0.05, size=2000) for lbl in fold_labels]
    p = block_bootstrap_p(fold_labels, fold_preds, B=200, seed=0)
    assert p < 0.05


def test_block_bootstrap_p_is_large_for_unrelated_series():
    rng = np.random.default_rng(1)
    fold_labels = [rng.normal(size=2000) for _ in range(5)]
    fold_preds = [rng.normal(size=2000) for _ in range(5)]
    p = block_bootstrap_p(fold_labels, fold_preds, B=200, seed=0)
    assert p > 0.01


def test_evaluate_gates_tradeable_lead():
    fold_ics = [0.08, 0.09, 0.08, 0.10, 0.09]
    linear_fold_ics = [0.01, 0.01, 0.02, 0.01, 0.01]
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.001)
    assert verdict == Verdict.TRADEABLE_LEAD


def test_evaluate_gates_linear_only_when_gbm_adds_nothing():
    fold_ics = [0.08, 0.09, 0.08, 0.10, 0.09]
    linear_fold_ics = [0.08, 0.09, 0.08, 0.10, 0.09]  # GBM == baseline exactly
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.001)
    assert verdict == Verdict.LINEAR_ONLY


def test_evaluate_gates_real_but_subthreshold():
    fold_ics = [0.01, 0.02, 0.01, 0.02, 0.01]  # real, below the 0.0726 floor
    linear_fold_ics = [0.001, 0.001, 0.001, 0.001, 0.001]
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.001)
    assert verdict == Verdict.REAL_BUT_SUBTHRESHOLD


def test_evaluate_gates_closed_when_not_significant():
    fold_ics = [0.001, -0.001, 0.001, -0.001, 0.001]
    linear_fold_ics = [0.0, 0.0, 0.0, 0.0, 0.0]
    verdict = evaluate_gates(fold_ics, linear_fold_ics, p_value=0.9)
    assert verdict == Verdict.CLOSED
