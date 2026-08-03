import numpy as np
import pytest

import cq.research.bar_sequence.models as bsm
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
    fold = Fold(
        0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000
    )
    returns = _synthetic_returns(400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000

    fit = select_fold_models(returns, decision_ts_ms, fold, feature_set)

    assert fit.lookback_n in (10, 20, 40)
    assert len(fit.test_label) == len(fit.logistic_pred) == len(fit.gbm_pred)
    assert len(fit.test_label) > 0
    assert set(np.unique(np.sign(fit.logistic_pred - 0.5))) <= {-1.0, 0.0, 1.0}


def test_select_fold_models_rejects_unknown_feature_set():
    fold = Fold(
        0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000
    )
    returns = _synthetic_returns(400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000
    with pytest.raises(ValueError):
        select_fold_models(returns, decision_ts_ms, fold, "not-a-real-feature-set")


def test_logistic_c_search_standardizes_on_inner_train_rows_only(monkeypatch):
    """Regression test for the standardization-asymmetry fix.

    Before the fix, the logistic C-search stage standardized ret_window using
    the *full* outer-train mask -- which includes the inner-validation rows
    the C-search scores itself against. That leaks the inner-validation rows'
    own scale into the statistics used to standardize them.

    This spies on every call to `standardize` made from inside
    `select_fold_models` and checks the calls made for the chosen lookback N:
    there must be a *dedicated* inner-train-only standardization call for the
    C-search (distinct from, and with a strictly smaller true-count than, the
    final full-train-window call). Under the pre-fix code there were only two
    standardize calls at the chosen N's window length (the N/GBM-loop's
    inner-train call and one shared full-train call reused for both the
    C-search and the final fit) -- this test fails against that code because
    it asserts a third, dedicated call exists.
    """
    fold = Fold(
        0, 100 * 300_000, 100 * 300_000 + 86_400_000, 100 * 300_000 + 86_400_000 + 50 * 300_000
    )
    returns = _synthetic_returns(400)
    decision_ts_ms = fold.train_start_ms + np.arange(1, len(returns) + 1) * 300_000

    calls = []
    real_standardize = bsm.standardize

    def spy_standardize(ret_window, train_rows):
        calls.append(np.asarray(train_rows).copy())
        return real_standardize(ret_window, train_rows)

    monkeypatch.setattr(bsm, "standardize", spy_standardize)

    fit = select_fold_models(returns, decision_ts_ms, fold, "ret")

    # Every standardize() call's mask length equals len(k) for whatever N
    # produced it; distinct N values in LOOKBACK_GRID always produce distinct
    # window lengths, so grouping by mask length isolates exactly the calls
    # made while working with the chosen N.
    chosen_k_len = len(returns) - fit.lookback_n
    chosen_n_calls = [c for c in calls if len(c) == chosen_k_len]

    # N/GBM-loop's inner-train call, the C-search's inner-train call, and the
    # final full-train call -- three distinct standardize() invocations.
    assert len(chosen_n_calls) == 3, (
        f"expected 3 standardize() calls at the chosen N's window length, got "
        f"{len(chosen_n_calls)}; the dedicated inner-train-only call for the "
        f"logistic C-search appears to be missing"
    )

    loop_call, c_search_call, final_call = chosen_n_calls

    # The N/GBM-loop call and the C-search call must both be inner-train-only
    # (same construction, same positions) and strictly smaller than the final
    # full-train call.
    assert np.array_equal(loop_call, c_search_call)
    assert c_search_call.sum() < final_call.sum()
    assert c_search_call.sum() == pytest.approx(final_call.sum() * 0.85, abs=2)
