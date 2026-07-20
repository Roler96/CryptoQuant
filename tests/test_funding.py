"""Funding models.

The rule that matters: a settlement inside the tested range that is not in
the archive is an error. OKX serves ~3 months of history, so most of a
five-year swap backtest has no measured rate — and a missing rate silently
read as zero is indistinguishable from a free hold, which is exactly the kind
of quiet optimism this project keeps finding after the fact.
"""

import pytest

from cq.core.clock import HOUR_MS
from cq.data.store import Store
from cq.engine.funding import (
    SETTLEMENT_INTERVAL_MS,
    ActualFunding,
    AssumedFunding,
    MissingFundingError,
    NoFunding,
    load_actual_funding,
    settlement_times,
)

DAY0 = 1_609_459_200_000  # 2021-01-01 00:00 UTC, itself a settlement instant


# ---- the settlement grid ----------------------------------------------


def test_settlements_land_on_the_okx_grid():
    times = settlement_times(DAY0, DAY0 + 24 * HOUR_MS)
    assert times == [DAY0, DAY0 + 8 * HOUR_MS, DAY0 + 16 * HOUR_MS]


def test_settlement_interval_is_eight_hours():
    assert SETTLEMENT_INTERVAL_MS == 8 * HOUR_MS


def test_range_start_is_inclusive_and_end_exclusive():
    # A settlement exactly at the end belongs to the next bar, not this one,
    # or it would be charged twice.
    assert settlement_times(DAY0, DAY0 + 8 * HOUR_MS) == [DAY0]
    assert settlement_times(DAY0 + 1, DAY0 + 8 * HOUR_MS) == []


def test_empty_range_yields_nothing():
    assert settlement_times(DAY0, DAY0) == []
    assert settlement_times(DAY0 + 100, DAY0) == []


def test_a_range_between_settlements_yields_nothing():
    assert settlement_times(DAY0 + HOUR_MS, DAY0 + 2 * HOUR_MS) == []


# ---- off ---------------------------------------------------------------


def test_off_yields_no_settlements_and_says_it_is_an_upper_bound():
    model = NoFunding()
    assert model.settlements(DAY0, DAY0 + 365 * 24 * HOUR_MS) == []
    assert "upper bound" in model.label


# ---- assumed -----------------------------------------------------------


def test_assumed_applies_a_constant_rate_on_the_grid():
    model = AssumedFunding(rate=0.0001)
    settlements = model.settlements(DAY0, DAY0 + 24 * HOUR_MS)
    assert [rate for _, rate in settlements] == [0.0001] * 3


def test_assumed_labels_itself_as_an_assumption():
    # It must never be mistaken for a measurement in a report.
    assert "assumption" in AssumedFunding(rate=0.0001).label
    assert "not a measurement" in AssumedFunding(rate=0.0001).label


# ---- actual ------------------------------------------------------------


def test_actual_returns_the_archived_rates():
    rates = {DAY0: 0.0001, DAY0 + 8 * HOUR_MS: -0.0002, DAY0 + 16 * HOUR_MS: 0.0003}
    model = ActualFunding(rates, "DOGE-USDT-SWAP")

    settlements = model.settlements(DAY0, DAY0 + 24 * HOUR_MS)

    assert settlements == [
        (DAY0, 0.0001),
        (DAY0 + 8 * HOUR_MS, -0.0002),
        (DAY0 + 16 * HOUR_MS, 0.0003),
    ]


def test_a_missing_settlement_raises_instead_of_becoming_zero():
    # The whole point of the three-mode design.
    rates = {DAY0: 0.0001}  # the 08:00 settlement is absent
    model = ActualFunding(rates, "DOGE-USDT-SWAP")

    with pytest.raises(MissingFundingError, match="no archived funding rate"):
        model.settlements(DAY0, DAY0 + 24 * HOUR_MS)


def test_the_error_names_the_instrument_and_offers_a_way_forward():
    model = ActualFunding({}, "DOGE-USDT-SWAP")
    with pytest.raises(MissingFundingError) as exc:
        model.settlements(DAY0, DAY0 + 8 * HOUR_MS)

    message = str(exc.value)
    assert "DOGE-USDT-SWAP" in message
    assert "funding=off" in message, "the error must say what to do instead"


def test_actual_is_fine_inside_its_archived_window():
    rates = {DAY0: 0.0001, DAY0 + 8 * HOUR_MS: 0.0002}
    model = ActualFunding(rates, "X")
    assert len(model.settlements(DAY0, DAY0 + 16 * HOUR_MS)) == 2


def test_covered_range_reports_what_is_actually_available():
    model = ActualFunding({DAY0: 0.1, DAY0 + 8 * HOUR_MS: 0.2}, "X")
    assert model.covered_range == (DAY0, DAY0 + 8 * HOUR_MS)
    assert ActualFunding({}, "X").covered_range is None


def test_actual_label_reports_how_many_settlements_it_has():
    assert "2 archived" in ActualFunding({DAY0: 0.1, DAY0 + 8 * HOUR_MS: 0.2}, "X").label


# ---- loading from the archive -----------------------------------------


def test_loading_from_the_store_round_trips(tmp_path):
    with Store(tmp_path / "test.db") as store:
        store.upsert_funding(
            [
                ("DOGE-USDT-SWAP", DAY0, 0.0001, 0.0001, 1),
                ("DOGE-USDT-SWAP", DAY0 + 8 * HOUR_MS, -0.0002, -0.0002, 1),
                ("BTC-USDT-SWAP", DAY0, 0.9, 0.9, 1),
            ]
        )

        model = load_actual_funding(store, "DOGE-USDT-SWAP")

        settlements = model.settlements(DAY0, DAY0 + 16 * HOUR_MS)
        assert settlements == [(DAY0, 0.0001), (DAY0 + 8 * HOUR_MS, -0.0002)]


def test_loading_does_not_mix_instruments(tmp_path):
    with Store(tmp_path / "test.db") as store:
        store.upsert_funding([("BTC-USDT-SWAP", DAY0, 0.9, 0.9, 1)])
        model = load_actual_funding(store, "DOGE-USDT-SWAP")
        assert model.covered_range is None
