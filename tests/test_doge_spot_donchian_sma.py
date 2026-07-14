"""Tests for DogeSpotDonchianSma strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from strategies.doge_spot_donchian_sma import DogeSpotDonchianSma


def _make_4h_df(closes: list[float], n_lead: int = 200) -> pd.DataFrame:
    """Build a 4h OHLCV frame with `n_lead` flat bars then ramps to `closes`.

    Each requested close gets one 4h bar that ramps from the previous close.
    """
    all_closes: list[float] = [100.0] * n_lead
    prev = 100.0
    for target in closes:
        all_closes.append(target)
        prev = target
    close = np.array(all_closes)
    start = pd.Timestamp("2024-01-01 00:00")
    dates = pd.date_range(start, periods=len(close), freq="4h")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(len(close), 10000.0),
        },
        index=dates,
    )


class TestDogeSpotDonchianSma:
    def test_flat_data_no_signal(self):
        df = _make_4h_df([100.0] * 50)
        signal = DogeSpotDonchianSma().generate_signal(df)
        assert (signal == 0).all()

    def test_long_only_never_short(self):
        # Strong uptrend should trigger long, never short
        ups = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(ups)
        signal = DogeSpotDonchianSma().generate_signal(df)
        assert (signal == -1).sum() == 0
        assert (signal == 1).any()

    def test_bear_market_stays_flat(self):
        # Persistent decline: SMA gate should block entry
        downs = [100 * 0.98**i for i in range(1, 100)]
        df = _make_4h_df(downs)
        signal = DogeSpotDonchianSma().generate_signal(df)
        assert (signal == 0).all()

    def test_breakout_above_sma_enters_long(self):
        # Build data where price is above SMA and breaks Donchian channel
        closes = [100.0] * 50 + [100 * 1.01**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        signal = DogeSpotDonchianSma().generate_signal(df)
        assert (signal == 1).any()

    def test_exit_on_channel_breakdown(self):
        # Rise to trigger entry, then fall below exit channel
        closes = [100 * 1.02**i for i in range(1, 80)]
        closes += [closes[-1] * 0.95**i for i in range(1, 60)]
        df = _make_4h_df(closes)
        signal = DogeSpotDonchianSma().generate_signal(df)
        # Should have entered and then exited
        assert (signal == 1).any()
        # After the decline, should be flat
        last_20 = signal.iloc[-20:]
        assert (last_20 == 0).all()

    def test_exit_on_trend_reversal(self):
        # Rise to enter, then cross below SMA (slow decline)
        closes = [100 * 1.03**i for i in range(1, 60)]
        # Then decline enough to cross below SMA(30) on daily
        closes += [closes[-1] * 0.99**i for i in range(1, 200)]
        df = _make_4h_df(closes)
        signal = DogeSpotDonchianSma().generate_signal(df)
        assert (signal == 1).any()
        # Eventually should exit when daily trend flips
        assert (signal.iloc[-20:] == 0).all()

    def test_insufficient_bars_raises(self):
        df = _make_4h_df([101.0], n_lead=50)
        with pytest.raises(StrategyError):
            DogeSpotDonchianSma().generate_signal(df)

    def test_output_shape_and_dtype(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        signal = DogeSpotDonchianSma().generate_signal(df)
        assert len(signal) == len(df)
        assert signal.index.equals(df.index)
        assert signal.dtype == int

    def test_custom_params(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        # Smaller entry_bars should trigger earlier
        strict = DogeSpotDonchianSma()
        loose = DogeSpotDonchianSma(params={"entry_bars": 10, "exit_bars": 5})
        sig_strict = strict.generate_signal(df)
        sig_loose = loose.generate_signal(df)
        # Loose config should enter no later than strict
        strict_entries = sig_strict[sig_strict == 1]
        loose_entries = sig_loose[sig_loose == 1]
        if len(strict_entries) > 0 and len(loose_entries) > 0:
            assert loose_entries.index[0] <= strict_entries.index[0]

    def test_invalid_params_raise(self):
        with pytest.raises(StrategyError):
            DogeSpotDonchianSma(params={"sma_period": 1})
        with pytest.raises(StrategyError):
            DogeSpotDonchianSma(params={"entry_bars": 5, "exit_bars": 10})
        with pytest.raises(StrategyError):
            DogeSpotDonchianSma(params={"entry_bars": -1})

    def test_generate_signal_for_position_flat(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        sig = DogeSpotDonchianSma().generate_signal_for_position(df, None)
        assert (sig >= 0).all()  # never short

    def test_generate_signal_for_position_long_exit(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        closes += [closes[-1] * 0.95**i for i in range(1, 60)]
        df = _make_4h_df(closes)
        sig = DogeSpotDonchianSma().generate_signal_for_position(df, "long")
        # Exit signal (0) should appear after the decline
        assert (sig == 0).any()

    def test_generate_signal_for_position_unsupported_side(self):
        df = _make_4h_df([100.0] * 50)
        with pytest.raises(StrategyError):
            DogeSpotDonchianSma().generate_signal_for_position(df, "short")
