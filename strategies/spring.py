"""Spring Reversal — Wyckoff Spring pattern with regime filters.

v1.0.0 — Filtered Spring: SMA200 + BB %B 0.2-0.6 regime filters.
         Backtest (OKX BTC/USDT 1h, 2019-2026, commission=5bps round-trip, slippage=5bps):
           Baseline (no filters):    Sharpe -0.71, Cmpd -46.0%, MaxDD -55.0%, 543 trades
           SMA200 only:              Sharpe +0.15, Cmpd  -0.1%, MaxDD -21.1%, 156 trades
           SMA200 + BB 0.2-0.6:      Sharpe +1.53, Cmpd +26.0%, MaxDD  -5.5%,  78 trades
           WF (6 splits):            5/6 profitable, mean OOS Sharpe +0.65
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    spring_reversal_signal, sma, bollinger_bands,
)


class SpringReversal(Strategy):
    """Spring Reversal strategy with SMA200 + BB %B 0.2-0.6 regime filters.

    Detects Wyckoff Spring patterns — failed breakdowns where price makes
    a new low below recent support but closes bullish with high volume,
    trapping sellers and signaling a reversal.

    The SMA200 trend filter and Bollinger %B zone filter are ESSENTIAL.
    Without them, the baseline strategy has Sharpe -0.71 and MaxDD -55%.
    The filters eliminate entries during sustained downtrends (71% of
    unfiltered signals) and restrict entries to the BB bounce zone where
    Springs are genuine reversals, not falling knives.

    Parameters:
        lookback: int = 20            Bars for support level and volume avg
        vol_mult: float = 1.5         Volume multiplier (1.5 = 150% of avg)
        close_pct: float = 0.5        Close must be above this fraction of bar range
        stop_pct: float = 3.0         Stop loss (%)
        target_pct: float = 2.5       Take profit (%)
        hold_hours: int = 24          Max position hold time
        commission: float = 0.0005    Round-trip cost estimate
        sma200_filter: bool = True    Enable SMA200 trend filter
        bb_filter: bool = True        Enable BB %B 0.2-0.6 zone filter
        bb_period: int = 20           Bollinger Band period
        bb_std: float = 2.0           Bollinger Band standard deviations
        bb_low: float = 0.2           BB %B lower bound (inclusive)
        bb_high: float = 0.6          BB %B upper bound (exclusive)
    """

    timeframe = "1h"
    min_bars = 300  # for SMA200 calculation
    version = "1.0.0"

    DEFAULT_PARAMS = {
        # Signal generation
        "lookback": 20,
        "vol_mult": 1.5,
        "close_pct": 0.5,
        # Exit parameters
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "hold_hours": 24,
        "commission": 0.0005,
        # Regime filters
        "sma200_filter": True,
        "bb_filter": True,
        "bb_period": 20,
        "bb_std": 2.0,
        "bb_low": 0.2,
        "bb_high": 0.6,
    }

    @property
    def name(self) -> str:
        return "SpringReversal"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        # Core Spring signal
        signal = spring_reversal_signal(
            df,
            lookback=self.params["lookback"],
            vol_mult=self.params["vol_mult"],
            close_pct=self.params["close_pct"],
        )

        # SMA200 trend filter: only trade above SMA200
        # Research: above SMA200 Sharpe +0.15, below SMA200 Sharpe -0.93
        # Without this filter, 71% of trades are in the toxic below-SMA200 zone
        if self.params.get("sma200_filter", True):
            sma200 = sma(df["close"], 200)
            signal = signal & (df["close"] > sma200)

        # BB %B zone filter: restrict to bounce zone [0.2, 0.6)
        # Research: %B 0.2-0.4 Sharpe +2.18, %B 0.4-0.6 Sharpe +1.68
        #            %B < 0.2 Sharpe -2.34 (free-fall zone — avoid)
        #            %B > 0.8 Sharpe near 0 (overextended — no edge)
        if self.params.get("bb_filter", True):
            bb = bollinger_bands(
                df,
                period=self.params["bb_period"],
                std=self.params["bb_std"],
            )
            pct_b = bb["pct_b"]
            signal = signal & (
                (pct_b >= self.params["bb_low"])
                & (pct_b < self.params["bb_high"])
            )

        return signal.astype(int)
