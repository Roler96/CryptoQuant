"""Volatility Spike + Bollinger Band Reversal with ADX Regime Filter.

Mean-reversion strategy gated to ranging markets (ADX < 20). Enters on
volatility spike + BB extreme + volume surge + extreme returns Z-score
— but ONLY when the market is not trending. Addresses the RSIBBMeanReversion
anti-pattern by adding an ADX regime gate.

Entry (long):  BB position < 0.1 AND vol spike > 1.5 AND volume ratio > 1.3
               AND Z-score < -2.0 AND ADX < 20
Entry (short): BB position > 0.9 AND vol spike > 1.5 AND volume ratio > 1.3
               AND Z-score > 2.0 AND ADX < 20
Exit:          Price returns to BB middle band (50% retracement)
Stop-loss:     Fixed percentage from entry
Max hold:      Time-based exit after N bars
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import adx, bollinger_bands, historical_volatility, volume_profile_ratio


class VolSpikeReversal(Strategy):
    """Volatility Spike + BB Reversal with ADX Ranging Market Filter.

    Parameters:
        bb_period: Bollinger Band period
        bb_std: BB standard deviation multiplier
        vol_short: Short volatility lookback
        vol_long: Long volatility lookback
        vol_spike_threshold: Min volatility ratio for "spike"
        vol_ratio_period: Volume SMA period
        vol_ratio_threshold: Min volume ratio
        zscore_period: Returns Z-score lookback
        zscore_threshold: Z-score entry threshold
        adx_period: ADX lookback
        adx_max: Max ADX for ranging market entry
        stop_loss_pct: Stop loss percentage
        max_hold_bars: Maximum bars to hold
    """

    timeframe = "1h"
    min_bars = 300  # vol_long=100 + zscore_period=100 + bb_period=20, padded
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "vol_short": 20,
        "vol_long": 100,
        "vol_spike_threshold": 1.5,
        "vol_ratio_period": 20,
        "vol_ratio_threshold": 1.3,
        "zscore_period": 100,
        "zscore_threshold": 2.0,
        "adx_period": 14,
        "adx_max": 20,
        "stop_loss_pct": 0.03,
        "max_hold_bars": 48,
    }

    @property
    def name(self) -> str:
        return "VolSpikeReversal"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate mean-reversion signals gated to ranging markets.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        bb_period = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        vol_short = self.params["vol_short"]
        vol_long = self.params["vol_long"]
        vol_spike_threshold = self.params["vol_spike_threshold"]
        vol_ratio_period = self.params["vol_ratio_period"]
        vol_ratio_threshold = self.params["vol_ratio_threshold"]
        zscore_period = self.params["zscore_period"]
        zscore_threshold = self.params["zscore_threshold"]
        adx_period = self.params["adx_period"]
        adx_max = self.params["adx_max"]
        max_hold_bars = self.params["max_hold_bars"]

        # --- Indicators ---

        # Bollinger Bands: pct_b = (close - lower) / (upper - lower)
        bb = bollinger_bands(df, period=bb_period, std=bb_std)
        bb_pct = bb["pct_b"]
        bb_middle = bb["middle"]

        # Volatility spike: short-term vol / long-term vol
        hv_short = historical_volatility(close, period=vol_short, annualize=False)
        hv_long = historical_volatility(close, period=vol_long, annualize=False)
        vol_spike_ratio = hv_short / hv_long

        # Volume ratio
        vol_ratio = volume_profile_ratio(df, period=vol_ratio_period)

        # Returns Z-score
        log_returns = np.log(close / close.shift(1))
        zscore_mean = log_returns.rolling(zscore_period).mean()
        zscore_std = log_returns.rolling(zscore_period).std()
        zscore = (log_returns - zscore_mean) / zscore_std

        # ADX regime filter
        adx_df = adx(df, period=adx_period)
        adx_val = adx_df["adx"]
        ranging = adx_val < adx_max

        # --- Entry conditions ---

        # Long: near lower BB + vol spike + volume surge + extreme negative Z + ranging
        bb_near_lower = bb_pct < 0.1
        vol_spike = vol_spike_ratio > vol_spike_threshold
        vol_surge = vol_ratio > vol_ratio_threshold
        zscore_extreme_neg = zscore < -zscore_threshold

        long_entry = bb_near_lower & vol_spike & vol_surge & zscore_extreme_neg & ranging

        # Short: near upper BB + vol spike + volume surge + extreme positive Z + ranging
        bb_near_upper = bb_pct > 0.9
        zscore_extreme_pos = zscore > zscore_threshold

        short_entry = bb_near_upper & vol_spike & vol_surge & zscore_extreme_pos & ranging

        # --- Exit conditions ---

        # Exit long: price returns to BB middle (50% retracement)
        exit_long_signal = close > bb_middle
        # Exit short: price returns to BB middle
        exit_short_signal = close < bb_middle

        # --- Stateful signal generation ---
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0
        bars_in_trade = 0

        for i in range(n):
            if pd.isna(bb_middle.iloc[i]) or pd.isna(adx_val.iloc[i]):
                signal[i] = 0
                continue

            if position == 1:
                bars_in_trade += 1
                # Exit conditions
                if exit_long_signal.iloc[i] or bars_in_trade >= max_hold_bars:
                    position = 0
                    bars_in_trade = 0
            elif position == -1:
                bars_in_trade += 1
                if exit_short_signal.iloc[i] or bars_in_trade >= max_hold_bars:
                    position = 0
                    bars_in_trade = 0
            elif position == 0:
                bars_in_trade = 0
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal[i] = position

        return pd.Series(signal, index=df.index, dtype=int)
