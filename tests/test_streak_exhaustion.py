"""Tests for StreakExhaustionFade strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from strategies.streak_exhaustion import StreakExhaustionFade


def _make_df(hourly_closes: list[float], n_lead: int = 400) -> pd.DataFrame:
    """Build a 5m OHLCV frame whose hourly closes follow `hourly_closes`.

    Leads with `n_lead` flat bars so min_bars is satisfied, then one hour
    (12 bars) per requested close: bars ramp linearly from the previous
    close to the target so the hour's last 5m bar carries the hourly close.
    """
    closes: list[float] = [100.0] * n_lead
    prev = 100.0
    for target in hourly_closes:
        steps = np.linspace(prev, target, 13)[1:]
        closes.extend(steps)
        prev = target
    close = np.array(closes)
    # Align so the lead block ends exactly on an hour boundary
    start = pd.Timestamp("2024-01-01 00:00")
    offset = (-n_lead) % 12
    dates = pd.date_range(
        start + pd.Timedelta(minutes=5 * offset),
        periods=len(close),
        freq="5min",
    )
    return pd.DataFrame(
        {"open": close, "high": close + 0.01, "low": close - 0.01,
         "close": close, "volume": np.full(len(close), 1000.0)},
        index=dates,
    )


class TestStreakExhaustionFade:
    def test_flat_data_no_signal(self):
        df = _make_df([100.0] * 10)
        signal = StreakExhaustionFade().generate_signal(df)
        assert (signal == 0).all()

    def test_five_up_hours_triggers_short(self):
        # +30 bps per hour x5 = +150 bps cumulative, above the 50 bps floor
        ups = [100 * 1.003**i for i in range(1, 6)]
        df = _make_df(ups)
        signal = StreakExhaustionFade().generate_signal(df)
        assert (signal == -1).any()
        assert not (signal == 1).any()
        # Fires no earlier than the close of the 5th up hour
        first = signal[signal == -1].index[0]
        fifth_hour_close = df.index[-1]
        assert first == fifth_hour_close

    def test_four_up_hours_no_signal(self):
        ups = [100 * 1.003**i for i in range(1, 5)]
        df = _make_df(ups)
        signal = StreakExhaustionFade().generate_signal(df)
        assert (signal == 0).all()

    def test_down_streak_no_signal(self):
        downs = [100 * 0.997**i for i in range(1, 7)]
        df = _make_df(downs)
        signal = StreakExhaustionFade().generate_signal(df)
        assert (signal == 0).all()

    def test_small_magnitude_streak_filtered(self):
        # 5 up hours but only ~+2.5 bps each: cumulative < min_streak_ret
        ups = [100 * 1.000025**i for i in range(1, 6)]
        df = _make_df(ups)
        signal = StreakExhaustionFade().generate_signal(df)
        assert (signal == 0).all()

    def test_signals_only_on_hour_close_bars(self):
        ups = [100 * 1.003**i for i in range(1, 8)]
        df = _make_df(ups)
        signal = StreakExhaustionFade().generate_signal(df)
        fired = signal[signal == -1].index
        assert len(fired) > 0
        assert ((fired + pd.Timedelta("5min")).minute == 0).all()

    def test_streak_reset_by_down_hour(self):
        # 3 up, 1 down, 3 up: no run of 5, must not fire
        seq = [100.3, 100.6, 100.9, 100.4, 100.7, 101.0, 101.3]
        df = _make_df(seq)
        signal = StreakExhaustionFade().generate_signal(df)
        assert (signal == 0).all()

    def test_insufficient_bars_raises(self):
        df = _make_df([101.0], n_lead=50)
        with pytest.raises(StrategyError):
            StreakExhaustionFade().generate_signal(df)

    def test_output_shape_and_dtype(self):
        df = _make_df([100 * 1.003**i for i in range(1, 6)])
        signal = StreakExhaustionFade().generate_signal(df)
        assert len(signal) == len(df)
        assert signal.index.equals(df.index)
        assert signal.dtype == int

    def test_custom_params(self):
        # streak_len=3 fires on data that default k=5 ignores
        ups = [100 * 1.003**i for i in range(1, 4)]
        df = _make_df(ups)
        strict = StreakExhaustionFade()
        loose = StreakExhaustionFade(params={"streak_len": 3})
        assert (strict.generate_signal(df) == 0).all()
        assert (loose.generate_signal(df) == -1).any()
