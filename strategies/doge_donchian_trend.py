"""DOGE 4h symmetric Donchian trend strategy for OKX perpetual swaps.

Entry uses a 20-day breakout.  Position-aware exits use the opposite 10-day
channel; the live engine supplies the independent 20% intrabar trailing stop.
All channels are shifted by one bar to prevent look-ahead.
"""

import pandas as pd

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.base import Strategy


class DogeDonchianTrend(Strategy):
    """Low-frequency long/short trend follower for DOGE-USDT-SWAP."""

    timeframe = "4h"
    min_bars = 181
    version = "1.1.0"
    signal_is_position = True

    DEFAULT_PARAMS = {
        "entry_bars": 120,
        "exit_bars": 60,
    }

    @property
    def name(self) -> str:
        return "DogeDonchianTrend"

    def validate_params(self) -> bool:
        entry_bars = self.params["entry_bars"]
        exit_bars = self.params["exit_bars"]
        if not isinstance(entry_bars, int) or entry_bars < 2:
            raise StrategyError("entry_bars must be an integer >= 2")
        if not isinstance(exit_bars, int) or exit_bars < 2:
            raise StrategyError("exit_bars must be an integer >= 2")
        if exit_bars >= entry_bars:
            raise StrategyError("exit_bars must be smaller than entry_bars")
        return True

    def _channels(self, df: pd.DataFrame) -> tuple[pd.Series, ...]:
        high = df["high"]
        low = df["low"]
        entry_bars = self.params["entry_bars"]
        exit_bars = self.params["exit_bars"]
        return (
            high.rolling(entry_bars).max().shift(1),
            low.rolling(entry_bars).min().shift(1),
            high.rolling(exit_bars).max().shift(1),
            low.rolling(exit_bars).min().shift(1),
        )

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Return a persistent position signal for the backtest engine."""
        df = self.preprocess(df)
        close = df["close"]
        entry_high, entry_low, exit_high, exit_low = self._channels(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        for i in range(len(df)):
            if pd.isna(entry_high.iloc[i]) or pd.isna(exit_high.iloc[i]):
                continue
            if position == 1 and close.iloc[i] < exit_low.iloc[i]:
                position = -1 if close.iloc[i] < entry_low.iloc[i] else 0
            elif position == -1 and close.iloc[i] > exit_high.iloc[i]:
                position = 1 if close.iloc[i] > entry_high.iloc[i] else 0
            elif position == 0:
                if close.iloc[i] > entry_high.iloc[i]:
                    position = 1
                elif close.iloc[i] < entry_low.iloc[i]:
                    position = -1
            signal.iloc[i] = position
        return signal

    def generate_signal_for_position(
        self, df: pd.DataFrame, position_side: str | None
    ) -> pd.Series:
        df = self.preprocess(df)
        close = df["close"]
        entry_high, entry_low, exit_high, exit_low = self._channels(df)
        signal = pd.Series(0, index=df.index, dtype=int)

        if position_side is None:
            signal.loc[close > entry_high] = 1
            signal.loc[close < entry_low] = -1
        elif position_side == "long":
            signal.loc[close < exit_low] = -1
        elif position_side == "short":
            signal.loc[close > exit_high] = 1
        else:
            raise StrategyError(f"Unsupported position side: {position_side}")

        return signal
