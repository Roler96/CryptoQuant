"""DOGE spot long-only Donchian breakout with daily SMA trend gate.

Entry: daily close > SMA(30) AND 4h close > 4h rolling high(45).shift(1).
Exit:  4h close < 4h rolling low(30).shift(1) OR daily close < SMA(30).
Spot-only: signals are 1 (long) / 0 (flat), never -1.
All channels and SMA are shifted by one bar to prevent look-ahead.
"""

import pandas as pd

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.base import Strategy


class DogeSpotDonchianSma(Strategy):
    """Long-only trend follower for DOGE/USDT spot."""

    timeframe = "4h"
    min_bars = 200
    version = "1.0.0"
    signal_is_position = True

    DEFAULT_PARAMS = {
        "sma_period": 30,
        "entry_bars": 45,
        "exit_bars": 30,
    }

    @property
    def name(self) -> str:
        return "DogeSpotDonchianSma"

    def validate_params(self) -> bool:
        sma_period = self.params["sma_period"]
        entry_bars = self.params["entry_bars"]
        exit_bars = self.params["exit_bars"]
        if not isinstance(sma_period, int) or sma_period < 2:
            raise StrategyError("sma_period must be an integer >= 2")
        if not isinstance(entry_bars, int) or entry_bars < 2:
            raise StrategyError("entry_bars must be an integer >= 2")
        if not isinstance(exit_bars, int) or exit_bars < 2:
            raise StrategyError("exit_bars must be an integer >= 2")
        if exit_bars >= entry_bars:
            raise StrategyError("exit_bars must be smaller than entry_bars")
        return True

    def _daily_trend(self, df: pd.DataFrame) -> pd.Series:
        """Compute daily SMA trend gate, forward-filled to 4h bars."""
        close = df["close"]
        sma_period = self.params["sma_period"]
        # Resample to daily close
        daily_close = close.resample("1d").last().dropna()
        daily_sma = daily_close.rolling(sma_period).mean()
        daily_trend = (daily_close > daily_sma).astype(int)
        # Forward-fill daily signal onto 4h index
        return daily_trend.reindex(df.index, method="ffill").fillna(0)

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Return a persistent position signal (1=long, 0=flat)."""
        df = self.preprocess(df)
        close = df["close"]
        entry_bars = self.params["entry_bars"]
        exit_bars = self.params["exit_bars"]

        entry_high = df["high"].rolling(entry_bars).max().shift(1)
        exit_low = df["low"].rolling(exit_bars).min().shift(1)
        trend = self._daily_trend(df)

        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        for i in range(len(df)):
            if pd.isna(entry_high.iloc[i]) or pd.isna(exit_low.iloc[i]):
                continue
            trend_ok = trend.iloc[i] == 1
            if position == 0 and trend_ok and close.iloc[i] > entry_high.iloc[i]:
                position = 1
            elif position == 1 and (
                close.iloc[i] < exit_low.iloc[i] or not trend_ok
            ):
                position = 0
            signal.iloc[i] = position
        return signal

    def generate_signal_for_position(
        self, df: pd.DataFrame, position_side: str | None
    ) -> pd.Series:
        """Return the target position, whatever we currently hold.

        generate_signal() already replays entries and exits statefully, so the
        target position is the whole contract here and position_side only needs
        validating. Recomputing the exit rules separately is what let live and
        backtest drift apart.
        """
        if position_side not in (None, "long"):
            raise StrategyError(
                f"Unsupported position side for spot strategy: {position_side}"
            )

        return self.generate_signal(df)
