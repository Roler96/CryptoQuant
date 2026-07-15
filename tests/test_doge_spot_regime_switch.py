"""Tests for DogeSpotRegimeSwitch strategy."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from strategies.doge_spot_regime_switch import DogeSpotRegimeSwitch


def _make_4h_df(closes: list[float], n_lead: int = 181, volumes: list[float] | None = None) -> pd.DataFrame:
    """Build a 4h OHLCV frame with `n_lead` flat bars then the given closes.

    Each requested close gets one 4h bar.  When *volumes* is None, all bars
    use a constant volume of 10 000 so the volume ratio filter (vol / MA20)
    is ~1.0 throughout.
    """
    all_closes: list[float] = [100.0] * n_lead
    all_closes.extend(closes)
    close = np.array(all_closes, dtype=float)

    if volumes is None:
        all_vols = [10000.0] * len(close)
    else:
        all_vols = [10000.0] * n_lead + volumes
        # pad / trim to match
        all_vols = all_vols[: len(close)]
        if len(all_vols) < len(close):
            all_vols.extend([10000.0] * (len(close) - len(all_vols)))

    start = pd.Timestamp("2024-01-01 00:00")
    dates = pd.date_range(start, periods=len(close), freq="4h")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.array(all_vols, dtype=float),
        },
        index=dates,
    )


class TestDogeSpotRegimeSwitch:
    # ------------------------------------------------------------------ #
    #  Basic signal properties                                           #
    # ------------------------------------------------------------------ #

    def test_flat_data_no_signal(self):
        df = _make_4h_df([100.0] * 50)
        signal = DogeSpotRegimeSwitch().generate_signal(df)
        assert (signal == 0).all()

    def test_long_only_never_short(self):
        ups = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(ups)
        signal = DogeSpotRegimeSwitch().generate_signal(df)
        assert (signal == -1).sum() == 0
        assert (signal == 1).any()

    def test_output_shape_and_dtype(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        signal = DogeSpotRegimeSwitch().generate_signal(df)
        assert len(signal) == len(df)
        assert signal.index.equals(df.index)
        assert signal.dtype == int

    # ------------------------------------------------------------------ #
    #  Bull sub-strategy                                                 #
    # ------------------------------------------------------------------ #

    def test_bull_breakout_enters_long(self):
        # Price above SMA and breaking Donchian channel
        closes = [100.0] * 50 + [100 * 1.01**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        signal = DogeSpotRegimeSwitch().generate_signal(df)
        assert (signal == 1).any()

    def test_bear_market_bull_stays_flat(self):
        # Persistent decline: SMA gate should block bull entry
        downs = [100 * 0.98**i for i in range(1, 100)]
        df = _make_4h_df(downs)
        signal = DogeSpotRegimeSwitch().generate_signal(df)
        # Bull sub-strategy should not fire (but bear might, so just check
        # it's not all-long)
        assert (signal == 0).any()

    def test_bull_exit_on_channel_breakdown(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        closes += [closes[-1] * 0.95**i for i in range(1, 60)]
        df = _make_4h_df(closes)
        signal = DogeSpotRegimeSwitch().generate_signal(df)
        assert (signal == 1).any()
        last_20 = signal.iloc[-20:]
        assert (last_20 == 0).all()

    def test_bull_exit_on_trend_reversal(self):
        closes = [100 * 1.03**i for i in range(1, 60)]
        closes += [closes[-1] * 0.99**i for i in range(1, 200)]
        df = _make_4h_df(closes)
        signal = DogeSpotRegimeSwitch().generate_signal(df)
        assert (signal == 1).any()
        assert (signal.iloc[-20:] == 0).all()

    # ------------------------------------------------------------------ #
    #  Bear sub-strategy                                                 #
    # ------------------------------------------------------------------ #

    def test_bear_swing_enters_on_deep_drawdown(self):
        # Build a strong uptrend (to set a high 30-day peak), then a sharp
        # decline past -35% drawdown, with an up-bar and volume spike.
        # Need at least 180 4h bars of lead for the lookback window.
        peak_bars = [100 * 1.005**i for i in range(200)]  # ~200 bars up
        peak = peak_bars[-1]
        # Drop 40% from peak
        drop_bars = [peak * (1 - 0.40 * (i + 1) / 30) for i in range(30)]
        # Then an up-bar with high volume
        drop_bars.append(drop_bars[-1] * 1.03)
        vols = [10000.0] * len(peak_bars) + [10000.0] * 30 + [50000.0]

        df = _make_4h_df(peak_bars + drop_bars[200:], n_lead=0, volumes=vols)
        # Actually need n_lead for SMA warmup too; rebuild properly:
        all_closes = [100.0] * 181 + peak_bars + drop_bars
        all_vols = [10000.0] * (181 + len(peak_bars)) + [10000.0] * 30 + [50000.0]
        start = pd.Timestamp("2024-01-01 00:00")
        dates = pd.date_range(start, periods=len(all_closes), freq="4h")
        df = pd.DataFrame(
            {
                "open": all_closes,
                "high": [c + 0.5 for c in all_closes],
                "low": [c - 0.5 for c in all_closes],
                "close": all_closes,
                "volume": all_vols,
            },
            index=dates,
        )

        signal = DogeSpotRegimeSwitch().generate_signal(df)
        # The bear swing should have triggered a long entry at some point
        # during the deep drawdown
        assert (signal == 1).any()

    def test_bear_swing_respects_upbar_filter(self):
        # Build data where regime is clearly bear (price well below SMA)
        # and drawdown is deep, but every bar is a down-bar (no up-bar).
        # The bear sub-strategy should NOT enter without an up-bar confirmation.
        # 181 flat warmup → 200 bars up to a peak → slow decline to cross SMA
        # → sharp drop (all down-bars) reaching -40% drawdown.
        peak_bars = [100 * 1.005**i for i in range(200)]
        peak = peak_bars[-1]
        # Slow decline for 150 bars to ensure price falls below SMA(30)
        slow_decline = [peak * (0.998**i) for i in range(1, 151)]
        # Then sharp drop (all down-bars) for 50 bars
        after_slow = slow_decline[-1]
        sharp_drop = [after_slow * (0.99**i) for i in range(1, 51)]
        all_closes = [100.0] * 181 + peak_bars + slow_decline + sharp_drop
        all_vols = [10000.0] * len(all_closes)

        start = pd.Timestamp("2024-01-01 00:00")
        dates = pd.date_range(start, periods=len(all_closes), freq="4h")
        df = pd.DataFrame(
            {
                "open": all_closes,
                "high": [c + 0.5 for c in all_closes],
                "low": [c - 0.5 for c in all_closes],
                "close": all_closes,
                "volume": all_vols,
            },
            index=dates,
        )

        signal = DogeSpotRegimeSwitch().generate_signal(df)
        # The sharp_drop section (last 50 bars) is all down-bars with deep
        # drawdown in bear regime — no bear entry should fire.
        assert (signal.iloc[-50:] == 0).all()

    # ------------------------------------------------------------------ #
    #  Parameter validation                                              #
    # ------------------------------------------------------------------ #

    def test_insufficient_bars_raises(self):
        df = _make_4h_df([101.0], n_lead=50)
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch().generate_signal(df)

    def test_invalid_params_raise(self):
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch(params={"sma_period": 1})
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch(params={"entry_bars": 5, "exit_bars": 10})
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch(params={"entry_bars": -1})
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch(params={"bear_drawdown_thresh": 5})
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch(params={"bear_take_profit": -0.1})
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch(params={"bear_stop_loss": 0})

    def test_custom_params(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        strict = DogeSpotRegimeSwitch()
        loose = DogeSpotRegimeSwitch(params={"entry_bars": 10, "exit_bars": 5})
        sig_strict = strict.generate_signal(df)
        sig_loose = loose.generate_signal(df)
        strict_entries = sig_strict[sig_strict == 1]
        loose_entries = sig_loose[sig_loose == 1]
        if len(strict_entries) > 0 and len(loose_entries) > 0:
            assert loose_entries.index[0] <= strict_entries.index[0]

    # ------------------------------------------------------------------ #
    #  generate_signal_for_position                                      #
    # ------------------------------------------------------------------ #

    def test_for_position_flat_non_negative(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        df = _make_4h_df(closes)
        sig = DogeSpotRegimeSwitch().generate_signal_for_position(df, None)
        assert (sig >= 0).all()

    def test_for_position_long_exit(self):
        closes = [100 * 1.02**i for i in range(1, 80)]
        closes += [closes[-1] * 0.95**i for i in range(1, 60)]
        df = _make_4h_df(closes)
        sig = DogeSpotRegimeSwitch().generate_signal_for_position(df, "long")

        # The rally must actually put the target position long, otherwise the
        # exit assertion below would pass on an all-zero series.
        assert (sig == 1).any()
        # ...and the crash must target flat, not merely "no action".
        assert sig.iloc[-1] == 0

    def test_for_position_matches_generate_signal(self):
        """Live and backtest must read the same target position.

        These drifted once already: the live hook re-derived exits from
        position_side and silently never closed anything.
        """
        closes = [100 * 1.02**i for i in range(1, 80)]
        closes += [closes[-1] * 0.95**i for i in range(1, 60)]
        df = _make_4h_df(closes)
        strat = DogeSpotRegimeSwitch()

        for side in (None, "long"):
            pd.testing.assert_series_equal(
                strat.generate_signal_for_position(df, side),
                strat.generate_signal(df),
            )

    def test_for_position_unsupported_side(self):
        df = _make_4h_df([100.0] * 50)
        with pytest.raises(StrategyError):
            DogeSpotRegimeSwitch().generate_signal_for_position(df, "short")


class TestDailyGateCausality:
    """The daily SMA gate must never see its own day's later bars.

    resample("1D").last() stamps a day's final close onto that day's 00:00
    index, so ffilling it onto the 4h bars without a daily shift(1) hands
    every bar of the day a close up to 20h in its own future. That exact
    construct got DogeSpotDonchianSma vetoed on 2026-07-14 (Test +61% ->
    -5.9% once corrected), and this strategy shipped with it too.

    test_gate_is_prefix_invariant is pinned against the unshifted
    implementation, where it finds 42 offending bars. Two formulations
    were tried and rejected for staying green on the broken gate: an
    end-to-end prefix check on generate_signal() (the bull/bear state
    machine absorbs an isolated gate flip unless it lands on a decision
    bar), and perturbing a single day's final bar (whether the flip shows
    up depends on the sample).
    """

    @staticmethod
    def _frame(close: pd.Series) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1000.0,
            },
            index=close.index,
        )

    @staticmethod
    def _random_close(n: int = 600) -> pd.Series:
        idx = pd.date_range("2024-01-01", periods=n, freq="4h")
        rng = np.random.default_rng(11)
        return pd.Series(
            100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n))), index=idx
        )

    def test_gate_is_prefix_invariant(self):
        """The gate at bar i must not depend on bars after i."""
        close = self._random_close()
        df = self._frame(close)
        strategy = DogeSpotRegimeSwitch()
        full = strategy._daily_trend(df)

        offenders = [
            df.index[i]
            for i in range(200, len(df))
            if strategy._daily_trend(df.iloc[: i + 1]).iloc[-1] != full.iloc[i]
        ]
        assert not offenders, (
            f"{len(offenders)} bars change value once later bars are visible, "
            f"first at {offenders[0]} — the gate is reading its own future"
        )

    def test_gate_still_tracks_the_trend(self):
        """Causality must not be bought by making the gate inert."""
        idx = pd.date_range("2024-01-01", periods=400, freq="4h")
        rally = pd.Series(np.linspace(100, 300, 400), index=idx)
        gate = DogeSpotRegimeSwitch()._daily_trend(self._frame(rally))

        assert gate.iloc[-1] == 1, "a sustained rally must end with the gate open"
        assert gate.sum() > 0
