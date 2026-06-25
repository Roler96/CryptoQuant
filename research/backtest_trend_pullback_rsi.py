"""TrendPullbackRSI — RSI pullback entries with EMA trend filter.

Addresses the "Pure Mean Reversion Without Trend Filter" anti-pattern by requiring
price to be above EMA(200) for longs (below for shorts). Uses moderate RSI zones
(40-50 long, 50-60 short) to catch pullbacks within a trend, not reversals.

Entry (Long):  close > EMA(200) AND 40 <= RSI <= 50 AND RSI rising
Entry (Short): close < EMA(200) AND 50 <= RSI <= 60 AND RSI falling
Exit:         trend reversal (close crosses EMA(200))
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, rsi


class TrendPullbackRSI(Strategy):
    """RSI pullback strategy with mandatory EMA trend filter.

    Enters in the direction of the trend, using RSI dips (longs) or bounces
    (shorts) as entry timing. Directly fixes the RSIBBMeanReversion failure
    where buying RSIs<30 in a bull market meant buying genuinely weak assets.

    Parameters:
        ema_period: int = 200            Trend filter period
        rsi_period: int = 14             RSI calculation period
        rsi_low: float = 40              Lower bound of long entry zone
        rsi_high: float = 50             Upper bound of long entry zone
        rsi_short_low: float = 50        Lower bound of short entry zone
        rsi_short_high: float = 60       Upper bound of short entry zone
    """

    timeframe = "1h"
    min_bars = 250       # 200 for EMA + 14 for RSI + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ema_period": 200,
        "rsi_period": 14,
        "rsi_low": 40,
        "rsi_high": 50,          # long entry zone: 40-50
        "rsi_short_low": 50,
        "rsi_short_high": 60,    # short entry zone: 50-60
    }

    @property
    def name(self) -> str:
        return "TrendPullbackRSI"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        ema_period = self.params["ema_period"]
        rsi_period = self.params["rsi_period"]
        rsi_low = self.params["rsi_low"]
        rsi_high = self.params["rsi_high"]
        rsi_short_low = self.params["rsi_short_low"]
        rsi_short_high = self.params["rsi_short_high"]

        close = df["close"]

        # Calculate indicators
        ema_200 = ema(close, ema_period)
        rsi_vals = rsi(close, rsi_period)

        n = len(df)
        signal = pd.Series(0, index=df.index, dtype=int)

        in_position = False
        position_side = 0   # 1=long, -1=short

        for i in range(n):
            if in_position:
                # Check trend reversal exit
                # Long: exit when close crosses below EMA
                # Short: exit when close crosses above EMA
                if position_side == 1:
                    if pd.notna(ema_200.iloc[i]) and close.iloc[i] < ema_200.iloc[i]:
                        signal.iloc[i] = 0  # exit via signal_reverse
                        in_position = False
                    else:
                        signal.iloc[i] = 1  # stay long
                else:  # short
                    if pd.notna(ema_200.iloc[i]) and close.iloc[i] > ema_200.iloc[i]:
                        signal.iloc[i] = 0  # exit via signal_reverse
                        in_position = False
                    else:
                        signal.iloc[i] = -1  # stay short
            else:
                # Check entry conditions (only if indicators are valid)
                if pd.isna(ema_200.iloc[i]) or pd.isna(rsi_vals.iloc[i]):
                    continue

                is_uptrend = close.iloc[i] > ema_200.iloc[i]
                is_downtrend = close.iloc[i] < ema_200.iloc[i]

                rsi_val = rsi_vals.iloc[i]
                rsi_prev = rsi_vals.iloc[i - 1] if i > 0 else 50.0
                rsi_rising = rsi_val > rsi_prev
                rsi_falling = rsi_val < rsi_prev

                # Long entry: uptrend + RSI pullback to 40-50 zone + RSI starting to rise
                if (is_uptrend and rsi_low <= rsi_val <= rsi_high and rsi_rising):
                    signal.iloc[i] = 1
                    in_position = True
                    position_side = 1

                # Short entry: downtrend + RSI bounce to 50-60 zone + RSI starting to fall
                elif (is_downtrend and rsi_short_low <= rsi_val <= rsi_short_high and rsi_falling):
                    signal.iloc[i] = -1
                    in_position = True
                    position_side = -1

        return signal
