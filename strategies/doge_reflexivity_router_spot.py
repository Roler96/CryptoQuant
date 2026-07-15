"""DOGE spot router for two distinct forced-flow exhaustion mechanisms.

The strategy is intentionally event-driven rather than indicator-driven.  It
routes either a systemic crypto liquidation event (an extreme BTC selloff
with DOGE derivatives taking share from spot) or a DOGE-specific liquidation
event (an extreme beta-adjusted DOGE residual with persistent derivatives
participation) into one DOGE/USDT spot position.

Signals use closed hourly bars.  Backtests execute at the next bar/open; live
paper uses the first current-market proxy after that decision.  Positions hold
for twelve hours, and the frozen signal-to-signal cooldown is enforced here.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd

from cryptoquant.exceptions import StrategyError
from strategies.doge_attention_handoff_spot import DogeAttentionHandoffSpot


class DogeReflexivityRouterSpot(DogeAttentionHandoffSpot):
    """Long-only DOGE spot router for systemic and idiosyncratic shocks."""

    # A current residual quantile can depend on 90d of residuals, whose oldest
    # beta estimate in turn depends on 30d of returns.  The extra 48h rebuilds
    # the event cooldown when live_runner supplies a rolling history window.
    min_bars = 90 * 24 + 30 * 24 + 6 + 48 + 1
    version = "1.0.0-paper"

    DEFAULT_PARAMS = {
        **DogeAttentionHandoffSpot.DEFAULT_PARAMS,
        "residual_shock_hours": 6,
        "beta_history_hours": 30 * 24,
        "beta_min_history_hours": 14 * 24,
        "residual_history_hours": 90 * 24,
        "residual_min_history_hours": 30 * 24,
        "residual_quantile": 0.01,
    }

    @property
    def name(self) -> str:
        return "DogeReflexivityRouterSpot"

    def __init__(self, params: dict[str, Any] | None = None):
        super().__init__(params)
        feature_history = max(
            self.params["shock_history_hours"] + self.params["btc_shock_hours"],
            self.params["beta_history_hours"]
            + self.params["residual_history_hours"]
            + self.params["residual_shock_hours"],
        )
        # Instance-level so an explicitly overridden research window cannot
        # silently receive the default live lookback.
        self.min_bars = feature_history + self.params["cooldown_hours"] + 1

    def validate_params(self) -> bool:
        super().validate_params()
        integer_bounds = {
            "residual_shock_hours": 2,
            "beta_history_hours": 24,
            "beta_min_history_hours": 24,
            "residual_history_hours": 24,
            "residual_min_history_hours": 24,
        }
        for key, lower in integer_bounds.items():
            value = self.params[key]
            if not isinstance(value, int) or value < lower:
                raise StrategyError(f"{key} must be an integer >= {lower}")
        if self.params["beta_min_history_hours"] > self.params["beta_history_hours"]:
            raise StrategyError(
                "beta_min_history_hours cannot exceed beta_history_hours"
            )
        if (
            self.params["residual_min_history_hours"]
            > self.params["residual_history_hours"]
        ):
            raise StrategyError(
                "residual_min_history_hours cannot exceed residual_history_hours"
            )
        quantile = self.params["residual_quantile"]
        if not isinstance(quantile, (int, float)) or not 0 < quantile < 0.5:
            raise StrategyError("residual_quantile must be between 0 and 0.5")
        return True

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build causal systemic and DOGE-specific liquidation features."""
        base = super().build_features(df)
        doge_close = self._numeric_column(df, "close")
        btc_close = self._numeric_column(df, "btc_close")
        doge_return = self._log(doge_close).diff()
        btc_return = self._log(btc_close).diff()

        beta_history = self.params["beta_history_hours"]
        beta_min = self.params["beta_min_history_hours"]
        beta_numerator = cast(
            pd.Series,
            doge_return.rolling(beta_history, min_periods=beta_min).cov(btc_return),
        ).shift(1)
        beta_denominator = cast(
            pd.Series,
            btc_return.rolling(beta_history, min_periods=beta_min).var(),
        ).shift(1)
        beta = beta_numerator / beta_denominator.where(beta_denominator > 0)

        shock_hours = self.params["residual_shock_hours"]
        doge_impulse = cast(
            pd.Series,
            doge_return.rolling(shock_hours, min_periods=shock_hours).sum(),
        )
        btc_impulse = cast(
            pd.Series,
            btc_return.rolling(shock_hours, min_periods=shock_hours).sum(),
        )
        residual_impulse = doge_impulse - beta * btc_impulse
        residual_cut = (
            residual_impulse.rolling(
                self.params["residual_history_hours"],
                min_periods=self.params["residual_min_history_hours"],
            )
            .quantile(self.params["residual_quantile"])
            .shift(1)
        )

        attention = base["attention"]
        raw_systemic = base["raw_event"].astype(bool)
        raw_idiosyncratic = (
            (residual_impulse < residual_cut)
            & (attention > 0)
            & (attention.shift(1) > 0)
        ).fillna(False)

        features = base.copy()
        features["doge_btc_beta"] = beta
        features["residual_impulse"] = residual_impulse
        features["residual_cut"] = residual_cut
        features["raw_systemic_event"] = raw_systemic
        features["raw_idiosyncratic_event"] = raw_idiosyncratic
        features["raw_event"] = raw_systemic | raw_idiosyncratic
        return features

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Route the first raw event in each frozen 48-hour event cluster."""
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
