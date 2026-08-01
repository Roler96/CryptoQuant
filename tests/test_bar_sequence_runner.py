"""End-to-end orchestration smoke tests for the bar-sequence-GBM runner."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("sklearn", reason="sklearn is required for runner orchestration tests")

from cq.data.store import Store
from cq.research.bar_sequence.stats import Verdict


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


def _build_synthetic_bars(store: Store, seed: int = 0, n_bars: int = 2_000):
    import cq.research.bar_sequence.data as data_mod

    rng = np.random.default_rng(seed)
    closes = 1.0 + np.cumsum(rng.normal(scale=0.001, size=n_bars))

    start_ms, _ = data_mod.explore_window()
    rows = []
    for i, close in enumerate(closes):
        ts = start_ms + i * 300_000
        open_price = float(close - 0.000_1)
        high = float(close + 0.000_1)
        low = float(close - 0.000_2)
        rows.append(
            (
                "DOGE-USDT",
                "5m",
                ts,
                open_price,
                high,
                low,
                float(close),
                10.0,
                float(10.0 * close),
            )
        )

    store.upsert_ohlcv(rows)
    return store.load_ohlcv("DOGE-USDT", "5m")


def _patch_inputs(monkeypatch, store: Store, seed: int = 0, n_bars: int = 2_000):
    import cq.research.bar_sequence.data as data_mod
    import cq.research.bar_sequence.folds as folds_mod

    frame = _build_synthetic_bars(store, seed=seed, n_bars=n_bars)
    monkeypatch.setattr(data_mod, "EXPECTED_RAW_FINGERPRINT", data_mod.data_fingerprint(frame))
    monkeypatch.setattr(data_mod, "EXPECTED_RAW_BAR_COUNT", len(frame))

    start_ms, _ = data_mod.explore_window()
    return (
        folds_mod.Fold(
            start_ms,
            start_ms + 800 * 300_000,
            start_ms + 800 * 300_000 + 86_400_000,
            start_ms + 1400 * 300_000,
        ),
        folds_mod.Fold(
            start_ms,
            start_ms + 1400 * 300_000,
            start_ms + 1400 * 300_000 + 86_400_000,
            start_ms + 1900 * 300_000,
        ),
    )


def test_run_study_shape_on_synthetic_data(store, monkeypatch):
    import cq.research.bar_sequence.folds as folds_mod
    import cq.research.bar_sequence.runner as runner_mod

    folds = _patch_inputs(monkeypatch, store)
    monkeypatch.setattr(runner_mod, "FOLDS", folds)

    report = runner_mod.run_study(store)

    assert report["study_tag"] == "doge-bar-sequence-gbm-v1"
    assert report["dropped_degenerate_bars"] == 0
    assert set(report["feature_sets"].keys()) == {"sign", "ret", "both"}

    for result in report["feature_sets"].values():
        assert result["verdict"] in {v.value for v in Verdict}
        assert isinstance(result["p_value"], float)
        assert len(result["fold_gbm_ic"]) == len(folds)
        assert len(result["fold_linear_ic"]) == len(folds)
        assert "shuffle_label_ic" in result
        assert "shuffle_label_p_value" in result

    # The local patching should target the runner module directly.
    assert folds_mod.FOLDS != runner_mod.FOLDS


def test_run_study_marks_invalid_on_a_leakage_hit(store, monkeypatch):
    import cq.research.bar_sequence.runner as runner_mod

    folds = _patch_inputs(monkeypatch, store)
    # One fold keeps the synthetic run fast and deterministic.
    monkeypatch.setattr(runner_mod, "FOLDS", (folds[0],))

    def fake_shuffle_predictions(returns, decision_ts_ms, fold, feature_set, seed, lookback_n=20):
        test_mask = (decision_ts_ms >= fold.test_start_ms) & (decision_ts_ms < fold.test_end_ms)
        label = np.linspace(-1.0, 1.0, int(test_mask.sum()))
        return label.copy(), label

    monkeypatch.setattr(runner_mod, "shuffle_label_predictions", fake_shuffle_predictions)

    report = runner_mod.run_study(store)
    for result in report["feature_sets"].values():
        assert result["verdict"] == Verdict.INVALID.value
