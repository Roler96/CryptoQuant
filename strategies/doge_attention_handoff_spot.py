"""DOGE spot event strategy driven by a cross-market participation handoff.

This is deliberately not a conventional price-indicator strategy.  It buys
DOGE/USDT spot only when an extreme BTC selloff coincides with DOGE perpetual
volume gaining participation relative to DOGE spot volume.  Signals are
formed on closed 1h bars and execute at the next bar/open through the engines.
"""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.base import MarketContext, Strategy


class DogeAttentionHandoffSpot(Strategy):
    """Long-only DOGE spot attention-handoff event strategy."""

    timeframe = "1h"
    # 90d threshold history + six-hour impulse + 48h cooldown reconstruction.
    min_bars = 90 * 24 + 6 + 48 + 1
    version = "1.0.0"
    signal_is_position = False
    max_hold_bars = 12
    execution_exchange = "okx"
    execution_symbol = "DOGE/USDT"
    execution_market_type = "spot"
    allows_external_exits = False

    context_markets = (
        MarketContext(
            alias="swap",
            historical_symbol="DOGE-USDT-SWAP",
            live_symbol="DOGE/USDT:USDT",
            columns=("volume",),
            market_type="swap",
        ),
        MarketContext(
            alias="btc",
            historical_symbol="BTC/USDT",
            live_symbol="BTC/USDT",
            columns=("close",),
        ),
    )

    DEFAULT_PARAMS = {
        "btc_shock_hours": 6,
        "btc_shock_quantile": 0.025,
        "shock_history_hours": 90 * 24,
        "shock_min_history_hours": 45 * 24,
        "volume_block_hours": 6,
        "attention_baseline_hours": 24,
        "cooldown_hours": 48,
    }

    @property
    def name(self) -> str:
        return "DogeAttentionHandoffSpot"

    def validate_params(self) -> bool:
        integer_bounds = {
            "btc_shock_hours": 2,
            "shock_history_hours": 24,
            "shock_min_history_hours": 24,
            "volume_block_hours": 2,
            "attention_baseline_hours": 6,
            "cooldown_hours": self.max_hold_bars or 1,
        }
        for key, lower in integer_bounds.items():
            value = self.params[key]
            if not isinstance(value, int) or value < lower:
                raise StrategyError(f"{key} must be an integer >= {lower}")

        quantile = self.params["btc_shock_quantile"]
        if not isinstance(quantile, (int, float)) or not 0 < quantile < 0.5:
            raise StrategyError("btc_shock_quantile must be between 0 and 0.5")
        if self.params["shock_min_history_hours"] > self.params["shock_history_hours"]:
            raise StrategyError(
                "shock_min_history_hours cannot exceed shock_history_hours"
            )
        return True

    @staticmethod
    def _numeric_column(df: pd.DataFrame, name: str) -> pd.Series:
        column = df[name]
        if not isinstance(column, pd.Series):  # pragma: no cover - scalar key
            raise StrategyError(f"Expected one Series for {name}")
        return column.astype(float)

    @staticmethod
    def _log(series: pd.Series) -> pd.Series:
        return pd.Series(
            np.log(series.to_numpy(dtype=float)),
            index=series.index,
            dtype=float,
        )

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return the causal mechanism features used by the entry rule."""
        df = self.preprocess(df)
        required = {"btc_close", "swap_volume"}
        missing = sorted(required.difference(df.columns))
        if missing:
            raise StrategyError(f"Missing market-context columns: {missing}")

        shock_hours = self.params["btc_shock_hours"]
        history = self.params["shock_history_hours"]
        min_history = self.params["shock_min_history_hours"]
        volume_hours = self.params["volume_block_hours"]
        attention_history = self.params["attention_baseline_hours"]

        btc_close = self._numeric_column(df, "btc_close")
        btc_impulse = self._log(btc_close).diff(shock_hours)
        btc_observation_count = cast(
            pd.Series,
            btc_close.notna()
            .rolling(shock_hours + 1, min_periods=shock_hours + 1)
            .sum(),
        )
        btc_window_complete = btc_observation_count.eq(shock_hours + 1)
        btc_shock_cut = (
            btc_impulse.shift(1)
            .rolling(history, min_periods=min_history)
            .quantile(self.params["btc_shock_quantile"])
        )

        spot_volume = self._numeric_column(df, "volume")
        swap_volume = self._numeric_column(df, "swap_volume")
        spot_block = cast(
            pd.Series,
            spot_volume.rolling(
                volume_hours, min_periods=volume_hours
            ).sum(),
        )
        swap_block = cast(
            pd.Series,
            swap_volume.rolling(
                volume_hours, min_periods=volume_hours
            ).sum(),
        )
        log_ratio = self._log(swap_block.where(swap_block > 0)) - self._log(
            spot_block.where(spot_block > 0)
        )
        # Shift by a full volume block so the current six-hour event cannot
        # contaminate its own 24-hour participation baseline.
        ratio_baseline = (
            log_ratio.shift(volume_hours)
            .rolling(attention_history, min_periods=attention_history)
            .median()
        )

        features = pd.DataFrame(index=df.index)
        features["btc_impulse"] = btc_impulse
        features["btc_shock_cut"] = btc_shock_cut
        features["btc_window_complete"] = btc_window_complete
        features["attention"] = log_ratio - ratio_baseline
        features["raw_event"] = (
            btc_window_complete
            & (btc_impulse < btc_shock_cut)
            & (features["attention"] > 0)
        ).fillna(False)
        return features

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Return causal long-entry pulses with a frozen event cooldown."""
        raw_event = self.build_features(df)["raw_event"].to_numpy(dtype=bool)
        signal = np.zeros(len(df), dtype=np.int8)
        blocked_until = -1
        cooldown = self.params["cooldown_hours"]
        for position in np.flatnonzero(raw_event):
            if position < blocked_until:
                continue
            signal[position] = 1
            blocked_until = position + cooldown
        return pd.Series(signal, index=df.index, dtype=int)
