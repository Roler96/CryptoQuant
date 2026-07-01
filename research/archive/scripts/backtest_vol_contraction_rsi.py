"""Volatility Contraction RSI Reversal strategy.

Bollinger Band squeeze (volatility contraction) as setup + RSI reversal as trigger.
When BB width contracts below a percentile threshold AND RSI crosses above oversold
(long) or below overbought (short), enter. Exit when RSI returns to neutral (50).

Signal convention: 1=long, -1=short, 0=flat.
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import bollinger_bands, crossover, crossunder, rsi


class VolContractionRSI(Strategy):
    """Volatility Contraction + RSI Reversal strategy.

    Entry:
        Long:  BB width < Nth percentile AND RSI crosses above oversold
        Short: BB width < Nth percentile AND RSI crosses below overbought

    Exit:
        Long:  RSI > exit_threshold (neutral)
        Short: RSI < exit_threshold (neutral)

    Uses per-bar state tracking: once in a trade, hold until exit condition met.
    Both long and short signals are generated.
    """

    timeframe = "1h"
    min_bars = 300
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "oversold_threshold": 30,
        "overbought_threshold": 70,
        "exit_threshold": 50,
        "squeeze_pct": 10,
        "squeeze_lookback": 100,
    }

    @property
    def name(self) -> str:
        return "VolContractionRSI"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate trading signals from OHLCV DataFrame.

        Args:
            df: OHLCV DataFrame with columns [open, high, low, close, volume]

        Returns:
            pd.Series of int signals: 1=long, -1=short, 0=flat.
        """
        df = self.preprocess(df)
        close = df["close"]

        # ── Parameters ──────────────────────────────────────────
        bb_period = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        rsi_period = self.params["rsi_period"]
        oversold = self.params["oversold_threshold"]
        overbought = self.params["overbought_threshold"]
        exit_thresh = self.params["exit_threshold"]
        squeeze_pct = self.params["squeeze_pct"] / 100.0
        squeeze_lookback = self.params["squeeze_lookback"]

        # ── Indicators ──────────────────────────────────────────
        bb = bollinger_bands(df, period=bb_period, std=bb_std)
        bb_width = bb["width"]
        rsi_val = rsi(close, period=rsi_period)

        # BB width percentile (rolling rank)
        bb_width_pctile = bb_width.rolling(squeeze_lookback).rank(pct=True)

        # Squeeze condition
        squeeze = bb_width_pctile < squeeze_pct

        # RSI crossover / crossunder signals
        long_entry_raw = crossover(rsi_val, pd.Series(oversold, index=df.index))
        short_entry_raw = crossunder(rsi_val, pd.Series(overbought, index=df.index))

        # Entry conditions
        long_entry = squeeze & (long_entry_raw == 1)
        short_entry = squeeze & (short_entry_raw == -1)

        # Exit conditions
        exit_long = rsi_val > exit_thresh
        exit_short = rsi_val < exit_thresh

        # ── State-machine forward pass ──────────────────────────
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        n = len(df)
        for i in range(n):
            if position == 0:
                # Flat — check for entry
                if long_entry.iloc[i]:
                    signal.iloc[i] = 1
                    position = 1
                elif short_entry.iloc[i]:
                    signal.iloc[i] = -1
                    position = -1

            elif position == 1:
                # Long — check for exit
                if exit_long.iloc[i]:
                    signal.iloc[i] = -1  # signal_reverse closes long
                    position = 0
                # else: hold — signal remains 0

            elif position == -1:
                # Short — check for exit
                if exit_short.iloc[i]:
                    signal.iloc[i] = 1  # signal_reverse closes short
                    position = 0
                # else: hold — signal remains 0

        return signal
