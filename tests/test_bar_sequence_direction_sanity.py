"""Protocol §7.3, second half: a synthetic monotonically increasing return
series where the "correct" model behavior is analytically known by
construction -- the actual model-selection path (Task 7's
select_fold_models) must learn it, not just an alignment index. This
complements Task 5's pure windowing/alignment check, which does not train
or evaluate any model."""

import numpy as np
import pytest

pytest.importorskip(
    "sklearn", reason="sklearn is required for direction-sanity model selection path"
)

from cq.research.bar_sequence.folds import Fold, fold_masks
from cq.research.bar_sequence.models import select_fold_models
from cq.research.bar_sequence.stats import rank_ic

MS_PER_BAR = 300_000
EMBARGO_MS = 86_400_000

N_BARS = 4_000
HOLDOUT_BLOCK = 100  # bars per held-out block
HOLDOUT_PERIOD = 5  # every 5th block is held out -> 20% of decision points


def _monotonic_series_with_held_out_blocks() -> tuple[np.ndarray, np.ndarray, Fold]:
    """A strictly increasing return series plus a genuine held-out split.

    Every `HOLDOUT_PERIOD`-th block of `HOLDOUT_BLOCK` consecutive bars is
    held out. The decision-time grid places every training bar in one early
    time window and every held-out bar in a strictly later one, so the fold
    satisfies `train_end_ms <= test_start_ms` and the two decision-timestamp
    sets are disjoint -- no decision point is ever both trained on and scored.

    Why held-out *blocks* rather than a plain forward cut: on a strictly
    monotonic series, a forward cut puts every test feature value strictly
    above the maximum seen in training. A histogram gradient-boosting model
    cannot extrapolate there by construction -- every such row lands in the
    top bin and receives an identical probability, so its test rank-IC is
    exactly 0 no matter how well it learned the relationship. That measures
    extrapolation, not the "模型能在此退化例子上学到解析已知的方向" property
    §7.3 asks for. Held-out blocks keep the test rows in-distribution while
    still being genuinely unseen. (The chronological *ordering* contract
    itself is covered by tests/test_bar_sequence_folds.py and the Fold
    invariant, not here.)
    """
    returns = np.linspace(-0.01, 0.01, N_BARS)

    index = np.arange(N_BARS)
    is_held_out = (index // HOLDOUT_BLOCK) % HOLDOUT_PERIOD == HOLDOUT_PERIOD - 1
    n_train_bars = int((~is_held_out).sum())
    n_test_bars = int(is_held_out.sum())

    decision_ts_ms = np.empty(N_BARS, dtype=np.int64)
    decision_ts_ms[~is_held_out] = (np.arange(n_train_bars) + 1) * MS_PER_BAR
    train_end_ms = (n_train_bars + 1) * MS_PER_BAR
    test_start_ms = train_end_ms + EMBARGO_MS
    decision_ts_ms[is_held_out] = test_start_ms + np.arange(n_test_bars) * MS_PER_BAR
    test_end_ms = test_start_ms + (n_test_bars + 1) * MS_PER_BAR

    fold = Fold(0, train_end_ms, test_start_ms, test_end_ms)
    return returns, decision_ts_ms, fold


def test_direction_sanity_fold_train_and_test_points_are_disjoint():
    """Guard against the regression this fixture was built to kill.

    An earlier version of this test used a fold whose "test" window fell
    *inside* its train window's range, so `fold_masks` marked the same
    decision points as both train and test -- and `assert_no_embargo_violation`
    cannot catch that, because its predicate is empty whenever
    train_end > test_end. The test was measuring in-sample fit.
    """
    _, decision_ts_ms, fold = _monotonic_series_with_held_out_blocks()

    train_mask, test_mask = fold_masks(decision_ts_ms, fold)

    assert train_mask.any()
    assert test_mask.any()
    assert not (train_mask & test_mask).any()
    train_ts = set(decision_ts_ms[train_mask].tolist())
    test_ts = set(decision_ts_ms[test_mask].tolist())
    assert train_ts.isdisjoint(test_ts)
    assert max(train_ts) < fold.train_end_ms <= fold.test_start_ms <= min(test_ts)


def test_model_recovers_the_known_direction_on_a_monotonic_series():
    # A strictly increasing, noise-free return series: consecutive returns
    # differ by a constant step, so r_{i+1} is a deterministic, monotonic
    # function of the recent window -- any competent model fit through the
    # real select_fold_models path must recover it with high rank-IC on rows
    # it never trained on. If this fails, the bug is in feature construction
    # or model selection (Task 7), not in this test.
    returns, decision_ts_ms, fold = _monotonic_series_with_held_out_blocks()

    fit = select_fold_models(returns, decision_ts_ms, fold, "ret")

    gbm_ic = rank_ic(fit.gbm_pred, fit.test_label)
    logistic_ic = rank_ic(fit.logistic_pred, fit.test_label)

    assert gbm_ic > 0.8, f"GBM should recover the known monotonic direction, got IC={gbm_ic}"
    assert logistic_ic > 0.8, f"Logistic baseline should recover it too, got IC={logistic_ic}"
