"""Wick Inversion — buy when sellers try hard and fail.

v4.4.0 — Added volatility gating (ATR ratio > 1.0 median) and SMA200 trend filter.
         Backtest (OKX BTC/USDT 1h, 2019-2026, commission=5bps round-trip, slippage=5bps):
           Baseline (no filters):  Sharpe -0.19, Cmpd -50.9%, MaxDD -60.6%, 2574 trades
           Vol gate only:          Sharpe +0.38, Cmpd +55.0%, MaxDD -40.5%, 1318 trades
           SMA200 only:            Sharpe +0.01, Cmpd -15.8%, MaxDD -51.0%, 1563 trades
           Vol+SMA200:             Sharpe +0.55, Cmpd +77.3%, MaxDD -23.3%, 821 trades
           WF mean OOS:            Sharpe +0.77 (5/6 splits positive)
         Note: earlier docstring quoted vol-gate-only numbers as Vol+SMA200; corrected.
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import wick_inversion_signal


class WickInversion(Strategy):
    """Wick Inversion strategy.

    Detects seller exhaustion via upper wick pressure + volume,
    enters long when imbalance exceeds threshold and price is not
    in free-fall.

    v4.4.0 filters:
      - Volatility gating: only trade when ATR(14) > 200-bar median ATR
      - Trend filter: only trade when price > SMA(200)

    Filter Rationale:
        Each filter exists for a specific empirical reason documented in
        ``docs/research/filter_rationale.md``.

        - **Volatility gating (ATR ratio > 1.0 median):** Removes low-vol
          chop where wicks are meaningless. Without it: Sharpe -0.19.
          With it: Sharpe +0.38. Never disable in standard deployment.
        - **SMA200 trend filter (price > SMA200):** Removes toxic entries
          during macro bear markets. Below SMA200 Sharpe -1.13; above
          SMA200 Sharpe +2.50. Optional to disable if running a short-biased
          variant (not implemented).

        See ``docs/research/filter_rationale.md`` for full backtest evidence,
        research sources, and disable guidance.

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
    version = "4.4.1"

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
        return wick_inversion_signal(df, **self.params)
