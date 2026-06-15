"""Wick Inversion — buy when sellers try hard and fail.

v4.4.0 — Added volatility gating (ATR ratio > 1.0 median) and SMA200 trend filter.
         Backtest (OKX BTC/USDT 1h, 2019-2026):
           Baseline:      Sharpe +1.14, Cmpd +77.6%, MaxDD -48.8%, 2574 trades
           Vol+SMA200:    Sharpe +2.22, Cmpd +199.4%, MaxDD -36.3%, 1318 trades
           WF mean OOS:   Sharpe +1.15 (5/6 splits positive)
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    pct_change_rolling, wick_imbalance, sma, atr as atr_func
)


class WickInversion(Strategy):
    """Wick Inversion strategy.

    Detects seller exhaustion via upper wick pressure + volume,
    enters long when imbalance exceeds threshold and price is not
    in free-fall.

    v4.4.0 filters:
      - Volatility gating: only trade when ATR(14) > 200-bar median ATR
      - Trend filter: only trade when price > SMA(200)

    Parameters:
        imbalance_window: int = 6     Rolling sum window for wick pressure
        imbalance_threshold: float = 0.25  Min seller/buyer imbalance
        price_lookback: int = 6       Price change calculation window (hours)
        price_floor: float = -0.5     Min 6h price change (%) to allow entry
        stop_pct: float = 3.0         Stop loss (%)
        target_pct: float = 1.5       Take profit (%)
        hold_hours: int = 12          Max position hold time
        commission: float = 0.0005    Round-trip cost estimate
        vol_gate_enabled: bool = True   Enable volatility gating
        trend_filter_enabled: bool = True  Enable SMA200 trend filter
    """

    timeframe = "1h"
    min_bars = 300  # increased from 100 for SMA200 calculation
    version = "4.4.0"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.25,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 1.5,
        "hold_hours": 12,
        "commission": 0.0005,
        "vol_gate_enabled": True,
        "trend_filter_enabled": True,
    }

    @property
    def name(self) -> str:
        return "WickInversion"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(
            df["close"], self.params["price_lookback"]
        )

        signal = (imb > self.params["imbalance_threshold"]) & (
            price_chg > self.params["price_floor"]
        )

        # v4.4.0: Volatility gating — only trade above-median volatility
        # Research shows: Very Low vol (<0.6x median) Sharpe -0.76
        #                 Low vol (0.6-0.8x)     Sharpe +0.37
        #                 Normal vol (0.8-1.2x)   Sharpe +1.44
        #                 High vol (1.2-1.5x)     Sharpe +1.62
        #                 Very High (>1.5x)       also positive
        # Best filter: vol_ratio > 1.0 keeps 41.6% of signals,
        #   Sharpe +2.22, MaxDD -36.3%, compound +199.4%
        if self.params.get("vol_gate_enabled", True):
            atr14 = atr_func(df, 14)
            median_atr = atr14.rolling(200).median()
            vol_ratio = atr14 / median_atr
            vol_ok = vol_ratio > 1.0  # above-median ATR
            signal = signal & vol_ok

        # v4.4.0: SMA200 trend filter — only trade above SMA200
        # Research shows: Above SMA200: Sharpe +2.50, PF 1.17
        #                 Below SMA200: Sharpe -1.13, PF 0.89
        if self.params.get("trend_filter_enabled", True):
            sma200 = sma(df["close"], 200)
            trend_ok = df["close"] > sma200
            signal = signal & trend_ok

        return signal.astype(int)
