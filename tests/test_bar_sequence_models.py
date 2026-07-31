import numpy as np
import pytest

from cq.research.bar_sequence.folds import Fold
from cq.research.bar_sequence.models import select_fold_models


def _synthetic_returns(n, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(scale=0.001, size=n)


def _decision_ts_for(returns, N, fold, ms_per_bar=300_000):
    # Enough bars, spaced 5m apart starting at the fold's train_start, to
    # populate both the train and test windows of the given fold.
    n_bars = len(returns) + 1
    return fold.train_start_ms + np.arange(1, n_bars) * ms_per_bar


@pytest.mark.parametrize("feature_set", ["sign", "ret", "both"])
def test_select_fold_models_returns_predictions_for_the_test_fold(feature_set):
    fold = Fold(0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000)
    returns = _synthetic_returns(400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000

    fit = select_fold_models(returns, decision_ts_ms, fold, feature_set)

    assert fit.lookback_n in (10, 20, 40)
    assert len(fit.test_label) == len(fit.logistic_pred) == len(fit.gbm_pred)
    assert len(fit.test_label) > 0
    assert set(np.unique(np.sign(fit.logistic_pred - 0.5))) <= {-1.0, 0.0, 1.0}


def test_select_fold_models_rejects_unknown_feature_set():
    fold = Fold(0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000)
    returns = _synthetic_returns(400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000
    with pytest.raises(ValueError):
        select_fold_models(returns, decision_ts_ms, fold, "not-a-real-feature-set")
