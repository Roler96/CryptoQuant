"""Strategy ensemble layer — combine multiple strategies into one signal."""
from typing import Any

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy


class StrategyEnsemble(Strategy):
    """Combine signals from multiple strategies.

    Methods:
        weighted_avg: Weighted average of signals, rounded to nearest integer.
        majority_vote: Most common signal wins; ties default to 0.
    """

    timeframe: str = "1h"
    min_bars: int = 1
    version: str = "1.0.0"

    def __init__(
        self,
        strategies: list[Strategy],
        weights: list[float] | None = None,
        method: str = "weighted_avg",
        params: dict[str, Any] | None = None,
    ):
        super().__init__(params)
        if not strategies:
            raise ValueError("strategies must not be empty")
        self.strategies = strategies
        self.weights = weights or [1.0] * len(strategies)
        if len(self.weights) != len(strategies):
            raise ValueError("weights length must match strategies length")
        self.method = method
        self.timeframe = strategies[0].timeframe
        self.min_bars = max(s.min_bars for s in strategies)

    @property
    def name(self) -> str:
        names = ",".join(s.name for s in self.strategies)
        return f"Ensemble({names})"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        signals = [s.generate_signal(df) for s in self.strategies]
        if self.method == "weighted_avg":
            combined = pd.Series(0.0, index=df.index)
            total_weight = sum(self.weights)
            for sig, w in zip(signals, self.weights):
                combined += sig.astype(float) * w
            combined /= total_weight
            return np.sign(combined).astype(int)
        elif self.method == "majority_vote":
            stacked = pd.concat(signals, axis=1)
            result = pd.Series(0, index=df.index, dtype=int)
            for idx in stacked.index:
                row = stacked.loc[idx]
                counts = row.value_counts()
                max_count = counts.max()
                top = counts[counts == max_count].index.tolist()
                if len(top) == 1:
                    result.loc[idx] = int(top[0])
                else:
                    result.loc[idx] = 0
            return result
        else:
            raise ValueError(f"Unknown ensemble method: {self.method}")
