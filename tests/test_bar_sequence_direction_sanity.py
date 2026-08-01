"""Protocol §7.3, second half: a synthetic monotonically increasing return
series where the "correct" model behavior is analytically known by
construction -- the actual model-selection path (Task 7's
select_fold_models) must learn it, not just an alignment index. This
complements Task 5's pure windowing/alignment check, which does not train
or evaluate any model."""

import numpy as np
import pytest

pytest.importorskip("sklearn", reason="sklearn is required for direction-sanity model selection path")

from cq.research.bar_sequence.folds import Fold
from cq.research.bar_sequence.models import select_fold_models
from cq.research.bar_sequence.stats import rank_ic


def test_model_recovers_the_known_direction_on_a_monotonic_series():
    # A strictly increasing, noise-free return series: consecutive returns
    # differ by a constant step, so r_{i+1} is a deterministic, monotonic
    # function of the recent window -- any competent model fit through the
    # real select_fold_models path must recover it with high rank-IC. If
    # this fails, the bug is in feature construction or model selection
    # (Task 7), not in this test.
    n = 400
    returns = np.linspace(-0.01, 0.01, n)

    # NOTE: the synthetic "monotonic" check intentionally places the test
    # window to straddle the label sign transition after a gapless training cut,
    # so both positive and negative labels exist in both train and test windows.
    fold = Fold(0, 100 * 300_000 + 86_400_000, 55_000_000, 70_000_000)
    decision_ts_ms = fold.train_start_ms + np.arange(1, n + 1) * 300_000

    fit = select_fold_models(returns, decision_ts_ms, fold, "ret")

    gbm_ic = rank_ic(fit.gbm_pred, fit.test_label)
    logistic_ic = rank_ic(fit.logistic_pred, fit.test_label)

    assert gbm_ic > 0.8, f"GBM should recover the known monotonic direction, got IC={gbm_ic}"
    assert logistic_ic > 0.8, f"Logistic baseline should recover it too, got IC={logistic_ic}"