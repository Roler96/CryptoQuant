from __future__ import annotations

from dataclasses import replace
from typing import cast

import numpy as np
import pandas as pd
import pytest

from cq.research.crdr.backtest import run_backtest
from cq.research.crdr.data import TRADE_INSTRUMENTS, StudyPanel
from cq.research.crdr.signals import SignalEvent


def _panel(exit_prices: tuple[float, float, float, float], *, hours: int = 12) -> StudyPanel:
    index = pd.date_range("2021-05-01", periods=hours, freq="1h", tz="UTC")
    columns = pd.Index(TRADE_INSTRUMENTS)
    opens = pd.DataFrame(100.0, index=index, columns=columns)
    for position, price in enumerate(exit_prices):
        opens.loc[index[7]:, TRADE_INSTRUMENTS[position]] = price
    closes = opens.copy()
    valid = pd.DataFrame(True, index=index, columns=columns)
    return StudyPanel(
        opens=opens,
        closes=closes,
        valid=valid,
        fingerprints={},
        raw_counts={},
        dropped_counts={},
    )


def _event(*, checkpoint_hour: int = 0, hold_hours: int = 6) -> SignalEvent:
    start = cast(pd.Timestamp, pd.Timestamp("2021-05-01", tz="UTC"))
    checkpoint = cast(pd.Timestamp, start + pd.Timedelta(hours=checkpoint_hour))
    entry_time = cast(pd.Timestamp, checkpoint + pd.Timedelta(hours=1))
    exit_time = cast(pd.Timestamp, checkpoint + pd.Timedelta(hours=1 + hold_hours))
    weights = {instrument: 0.0 for instrument in TRADE_INSTRUMENTS}
    weights[TRADE_INSTRUMENTS[0]] = 0.25
    weights[TRADE_INSTRUMENTS[1]] = 0.25
    weights[TRADE_INSTRUMENTS[2]] = -0.25
    weights[TRADE_INSTRUMENTS[3]] = -0.25
    return SignalEvent(
        checkpoint=checkpoint,
        entry_time=entry_time,
        exit_time=exit_time,
        dispersion=1.0,
        threshold=0.5,
        residuals=tuple(
            (instrument, float(rank)) for rank, instrument in enumerate(TRADE_INSTRUMENTS)
        ),
        weights=tuple(weights.items()),
    )


def test_fixed_contract_pnl_and_main_costs_match_hand_calculation() -> None:
    panel = _panel((110.0, 105.0, 90.0, 95.0))

    result = run_backtest(panel, [_event()], cost_bps=15)

    episode = result.episodes[0]
    expected_gross = 0.25 * (0.10 + 0.05 + 0.10 + 0.05)
    assert episode.gross_return == pytest.approx(expected_gross)
    assert episode.net_return == pytest.approx(expected_gross - 0.003)
    assert episode.long_net_return == pytest.approx(0.25 * (0.10 + 0.05) - 0.0015)
    assert episode.short_net_return == pytest.approx(0.25 * (0.10 + 0.05) - 0.0015)
    assert result.equity.iloc[-1] == pytest.approx(1.0 + episode.net_return)


def test_stress_cost_and_unknown_funding_penalty_total_55_bps() -> None:
    result = run_backtest(
        _panel((100.0, 100.0, 100.0, 100.0)),
        [_event()],
        cost_bps=25,
        funding_penalty_bps=5,
    )

    assert result.episodes[0].net_return == pytest.approx(-0.0055)
    assert result.equity.iloc[-1] == pytest.approx(0.9945)


def test_entry_and_exit_costs_land_on_the_frozen_open_timestamps() -> None:
    result = run_backtest(_panel((100.0, 100.0, 100.0, 100.0)), [_event()], cost_bps=15)
    entry = pd.Timestamp("2021-05-01 01:00", tz="UTC")
    exit_ = pd.Timestamp("2021-05-01 07:00", tz="UTC")

    assert result.equity.loc[entry] == pytest.approx(0.9985)
    assert result.equity.loc[exit_] == pytest.approx(0.9970)
    assert (result.hourly_returns.loc[exit_ + pd.Timedelta(hours=1):] == 0.0).all()


def test_intrahour_curve_uses_fixed_entry_notional_instead_of_rebalancing() -> None:
    panel = _panel((100.0, 100.0, 100.0, 100.0))
    opens = panel.opens.copy()
    first_long = TRADE_INSTRUMENTS[0]
    opens.loc[pd.Timestamp("2021-05-01 02:00", tz="UTC"):, first_long] = 200.0
    panel = replace(panel, opens=opens)

    result = run_backtest(panel, [_event()], cost_bps=0)

    assert result.equity.loc[pd.Timestamp("2021-05-01 02:00", tz="UTC")] == pytest.approx(1.25)
    assert result.equity.loc[pd.Timestamp("2021-05-01 07:00", tz="UTC")] == pytest.approx(1.25)


def test_overlapping_events_are_rejected() -> None:
    first = _event()
    overlapping = replace(
        _event(checkpoint_hour=1),
        entry_time=first.entry_time + pd.Timedelta(hours=2),
        exit_time=first.exit_time + pd.Timedelta(hours=2),
    )

    with pytest.raises(ValueError, match="overlap"):
        run_backtest(_panel((100.0, 100.0, 100.0, 100.0)), [first, overlapping], cost_bps=15)


def test_nonfinite_selected_leg_open_is_rejected() -> None:
    panel = _panel((100.0, 100.0, 100.0, 100.0))
    opens = panel.opens.copy()
    opens.loc[pd.Timestamp("2021-05-01 07:00", tz="UTC"), TRADE_INSTRUMENTS[0]] = np.nan

    with pytest.raises(ValueError, match="invalid execution open"):
        run_backtest(replace(panel, opens=opens), [_event()], cost_bps=15)


def test_continuation_weights_produce_the_exact_opposite_gross_return() -> None:
    event = _event()
    continuation = replace(
        event,
        weights=tuple((instrument, -weight) for instrument, weight in event.weights),
    )
    panel = _panel((110.0, 105.0, 90.0, 95.0))

    reversal_result = run_backtest(panel, [event], cost_bps=0)
    continuation_result = run_backtest(panel, [continuation], cost_bps=0)

    assert continuation_result.episodes[0].gross_return == pytest.approx(
        -reversal_result.episodes[0].gross_return
    )
