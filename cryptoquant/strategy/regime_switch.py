"""Regime-conditioned strategy switching — delegate to different strategies by market regime."""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import detect_regime


class RegimeSwitch(Strategy):
    """Switch strategies based on detected market regime.

    Uses ``detect_regime()`` to classify the current market state, then
    delegates signal generation to the strategy mapped to that regime.
    """

    DEFAULT_PARAMS = {
        "adx_period": 14,
        "vol_period": 20,
        "sma_period": 200,
        "adx_threshold": 25.0,
        "vol_high_pct": 70.0,
        "vol_low_pct": 30.0,
    }

    def __init__(
        self,
        regime_map: dict[str, Strategy],
        default: Strategy | None = None,
        params: dict | None = None,
    ):
        """
        Args:
            regime_map: Mapping from regime label to strategy.
                Keys must match labels returned by ``detect_regime()``.
            default: Fallback strategy when no regime matches or
                the mapped strategy is None.
            params: Override for ``DEFAULT_PARAMS``.
        """
        self.regime_map = regime_map
        self.default = default
        super().__init__(params)
        self._timeframe = None
        self._min_bars = None

    @property
    def name(self) -> str:
        return f"RegimeSwitch({','.join(self.regime_map.keys())})"

    @property
    def timeframe(self) -> str:
        if self._timeframe is None:
            self._timeframe = getattr(
                next(iter(self.regime_map.values())), "timeframe", "1h"
            )
        return self._timeframe

    @property
    def min_bars(self) -> int:
        if self._min_bars is None:
            self._min_bars = max(
                getattr(s, "min_bars", 0) for s in self.regime_map.values()
            )
        return self._min_bars

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        regimes = detect_regime(
            df,
            adx_period=self.params.get("adx_period", 14),
            vol_period=self.params.get("vol_period", 20),
            sma_period=self.params.get("sma_period", 200),
            adx_threshold=self.params.get("adx_threshold", 25.0),
            vol_high_pct=self.params.get("vol_high_pct", 70.0),
            vol_low_pct=self.params.get("vol_low_pct", 30.0),
        )
        current_regime = regimes.iloc[-1]
        strategy = self.regime_map.get(current_regime, self.default)
        if strategy is None:
            return pd.Series(0, index=df.index, dtype=int)
        return strategy.generate_signal(df)
