"""DOGE spot regime-switching strategy: bull Donchian + bear drawdown swing.

Bull regime (daily close > SMA(N)): 4h Donchian breakout long — same as
DogeSpotDonchianSma.

Bear regime (daily close < SMA(N)): deep drawdown swing — when price has
fallen >= drawdown_thresh from its 30-day high, wait for an up-bar with
above-average volume, then enter long.  Exit at take-profit, stop-loss,
max-hold timeout, or regime change back to bull.

Spot-only: signals are 1 (long) / 0 (flat), never -1.
All channels, SMA, and rolling high are shifted by one bar to prevent
look-ahead.
"""

import pandas as pd

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.base import Strategy


class DogeSpotRegimeSwitch(Strategy):
    """Regime-switching long-only strategy for DOGE/USDT spot."""

    timeframe = "4h"
    min_bars = 181
    version = "1.0.0"
    signal_is_position = True

    DEFAULT_PARAMS = {
        "sma_period": 30,
        "entry_bars": 45,
        "exit_bars": 30,
        "bear_lookback": 180,       # 30 days * 6 bars/day
        "bear_drawdown_thresh": -35.0,
        "bear_take_profit": 0.10,
        "bear_stop_loss": 0.10,
        "bear_max_hold": 45,        # 7.5 days in 4h bars
        "bear_vol_ma": 20,
        "bear_vol_min": 1.0,
    }

    @property
    def name(self) -> str:
        return "DogeSpotRegimeSwitch"

    def validate_params(self) -> bool:
        p = self.params
        for key in ("sma_period", "entry_bars", "exit_bars",
                    "bear_lookback", "bear_vol_ma", "bear_max_hold"):
            v = p[key]
            if not isinstance(v, int) or v < 2:
                raise StrategyError(f"{key} must be an integer >= 2")
        if p["exit_bars"] >= p["entry_bars"]:
            raise StrategyError("exit_bars must be smaller than entry_bars")
        for key in ("bear_drawdown_thresh",):
            if not isinstance(p[key], (int, float)) or p[key] >= 0:
                raise StrategyError(f"{key} must be negative")
        for key in ("bear_take_profit", "bear_stop_loss", "bear_vol_min"):
            v = p[key]
            if not isinstance(v, (int, float)) or v <= 0:
                raise StrategyError(f"{key} must be positive")
        return True

    # ------------------------------------------------------------------ #
    #  Indicators                                                        #
    # ------------------------------------------------------------------ #

    def _daily_trend(self, df: pd.DataFrame) -> pd.Series:
        """Daily SMA trend gate, forward-filled onto the 4h index.

        The daily shift(1) is load-bearing. resample("1D").last() stamps a
        day's *final* close onto that day's 00:00 index, so ffilling it
        straight onto the 4h bars hands every bar of the day a close up to
        20h in its own future — the look-ahead that got DogeSpotDonchianSma
        vetoed on 2026-07-14. Shifting a day back means each bar sees only
        the previous day's completed close.
        """
        close = df["close"]
        sma_period = self.params["sma_period"]
        daily_close = close.resample("1D").last().dropna()
        daily_sma = daily_close.rolling(sma_period).mean()
        daily_trend = (daily_close > daily_sma).astype(int).shift(1)
        return daily_trend.reindex(df.index, method="ffill").fillna(0)

    def _bull_channels(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        high = df["high"]
        low = df["low"]
        eb = self.params["entry_bars"]
        xb = self.params["exit_bars"]
        return (
            high.rolling(eb).max().shift(1),
            low.rolling(xb).min().shift(1),
        )

    def _bear_drawdown(self, df: pd.DataFrame) -> pd.Series:
        """Percentage drawdown from rolling high (shifted)."""
        lookback = self.params["bear_lookback"]
        roll_high = df["high"].rolling(lookback).max().shift(1)
        return (df["close"] / roll_high - 1) * 100

    def _vol_filter(self, df: pd.DataFrame) -> pd.Series:
        """Volume / rolling-average-volume, shifted to avoid look-ahead."""
        ma = self.params["bear_vol_ma"]
        vol_ma = df["volume"].rolling(ma).mean().shift(1)
        return df["volume"] / vol_ma.replace(0, pd.NA)

    # ------------------------------------------------------------------ #
    #  Signal generation                                                 #
    # ------------------------------------------------------------------ #

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Return a persistent position signal (1=long, 0=flat)."""
        df = self.preprocess(df)
        close = df["close"]
        entry_high, exit_low = self._bull_channels(df)
        trend = self._daily_trend(df)
        drawdown = self._bear_drawdown(df)
        vol_ratio = self._vol_filter(df)

        thresh = self.params["bear_drawdown_thresh"]
        tp = self.params["bear_take_profit"]
        sl = self.params["bear_stop_loss"]
        max_hold = self.params["bear_max_hold"]
        vol_min = self.params["bear_vol_min"]

        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0          # 0 = flat, 1 = long
        sub_strategy = ""     # "bull" or "bear"
        entry_price = 0.0
        tp_price = 0.0
        sl_price = 0.0
        entry_idx = 0

        values = close.values
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)

        for i in range(n):
            # --- exits -------------------------------------------------
            if position == 1:
                if sub_strategy == "bull":
                    trend_ok = trend.iloc[i] == 1
                    if not trend_ok or (
                        not pd.isna(exit_low.iloc[i])
                        and values[i] < exit_low.iloc[i]
                    ):
                        position = 0
                        sub_strategy = ""
                elif sub_strategy == "bear":
                    if (
                        lows[i] <= sl_price            # intrabar stop-loss
                        or highs[i] >= tp_price        # intrabar take-profit
                        or i - entry_idx >= max_hold
                        or trend.iloc[i] == 1          # regime back to bull
                    ):
                        position = 0
                        sub_strategy = ""

            # --- entries (only when flat) ------------------------------
            if position == 0:
                trend_ok = trend.iloc[i] == 1

                # Bull entry: trend up + Donchian breakout
                if trend_ok and not pd.isna(entry_high.iloc[i]) \
                        and values[i] > entry_high.iloc[i]:
                    position = 1
                    sub_strategy = "bull"

                # Bear entry: regime bear + deep drawdown + up-bar + vol
                elif not trend_ok \
                        and not pd.isna(drawdown.iloc[i]) \
                        and drawdown.iloc[i] <= thresh \
                        and i > 0 and values[i] > values[i - 1] \
                        and not pd.isna(vol_ratio.iloc[i]) \
                        and vol_ratio.iloc[i] >= vol_min:
                    position = 1
                    sub_strategy = "bear"
                    entry_price = values[i]
                    tp_price = entry_price * (1 + tp)
                    sl_price = entry_price * (1 - sl)
                    entry_idx = i

            signal.iloc[i] = position

        return signal

    def generate_signal_for_position(
        self, df: pd.DataFrame, position_side: str | None
    ) -> pd.Series:
        """Return the target position, whatever we currently hold.

        generate_signal() replays the bull/bear state machine, so it already
        knows which sub-strategy is active and where the bear leg's take-profit
        and stop-loss sit. Re-deriving exits from position_side alone cannot:
        the side says "long" for both legs, which is exactly how the bear leg's
        price exits ended up delegated to engine-level config that then applied
        to bull trades too.
        """
        if position_side not in (None, "long"):
            raise StrategyError(
                f"Unsupported position side for spot strategy: {position_side}"
            )

        return self.generate_signal(df)
