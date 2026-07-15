"""Research/production parity tests for the DOGE reflexivity router."""

import numpy as np
import pandas as pd
import pytest

import research_doge_attention_handoff as attention_research
import research_doge_reflexivity_router as router_research


def test_event_blocks_do_not_split_a_single_liquidation_cluster():
    events = pd.DataFrame(
        {
            "signal": pd.to_datetime(
                ["2025-01-01", "2025-01-03", "2025-01-10"]
            ),
            "return": [0.01, -0.02, 0.03],
        }
    )

    blocks = router_research._event_blocks(events)

    assert len(blocks) == 2
    np.testing.assert_allclose(blocks[0], [0.01, -0.02])
    np.testing.assert_allclose(blocks[1], [0.03])


def test_tail_audit_deletes_the_best_returns(monkeypatch):
    index = pd.date_range("2025-01-01", periods=200, freq="1h")
    frame = pd.DataFrame(
        {
            "open": np.linspace(1, 2, len(index)),
            "high": np.linspace(1, 2, len(index)),
            "low": np.linspace(1, 2, len(index)),
            "close": np.linspace(1, 2, len(index)),
            "volume": 1.0,
        },
        index=index,
    )
    snapshot = attention_research.MarketSnapshot(frame, frame, frame)
    raw = pd.Series(0, index=index, dtype=int)
    raw.iloc[[10, 80, 150]] = 1
    signals = router_research.RouteSignals(raw, raw, raw)
    monkeypatch.setattr(attention_research, "DEPLOY_POSITION_PCT", 10.0)

    result = router_research.tail_and_block_audit(
        snapshot,
        signals,
        simulations=100,
        seed=1,
    )

    assert (result["delete_1_return_pct"] < result["delete_0_return_pct"]).all()


def test_tail_audit_handles_an_empty_candidate(monkeypatch):
    index = pd.date_range("2025-01-01", periods=200, freq="1h")
    frame = pd.DataFrame(
        {
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        },
        index=index,
    )
    snapshot = attention_research.MarketSnapshot(frame, frame, frame)
    empty = pd.Series(0, index=index, dtype=int)
    signals = router_research.RouteSignals(empty, empty, empty)
    monkeypatch.setattr(attention_research, "DEPLOY_POSITION_PCT", 10.0)

    result = router_research.tail_and_block_audit(
        snapshot,
        signals,
        simulations=10,
    )

    assert (result["trades"] == 0).all()
    assert (result["blocks"] == 0).all()


def test_frozen_snapshot_guard_detects_candle_drift(monkeypatch):
    index = pd.date_range("2025-01-01", periods=20, freq="1h")
    frame = pd.DataFrame(
        {
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        },
        index=index,
    )
    snapshot = attention_research.MarketSnapshot(frame, frame.copy(), frame.copy())
    fingerprint = router_research.dataframe_fingerprint(frame)
    monkeypatch.setattr(
        router_research,
        "FROZEN_FINGERPRINTS",
        {
            "doge_spot": fingerprint,
            "doge_swap": fingerprint,
            "btc_spot": fingerprint,
        },
    )
    router_research.assert_frozen_snapshot(snapshot)

    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] = 1.01
    drifted = attention_research.MarketSnapshot(frame, frame.copy(), changed)
    with pytest.raises(RuntimeError, match="snapshot drifted"):
        router_research.assert_frozen_snapshot(drifted)
