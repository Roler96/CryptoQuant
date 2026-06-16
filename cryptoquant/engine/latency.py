"""Latency models for backtesting and simulation."""
from abc import ABC, abstractmethod

import numpy as np


class LatencyModel(ABC):
    """Abstract base class for fill-latency models."""

    @abstractmethod
    def bars_delay(self) -> int:
        """Return number of bars to delay fill."""
        ...


class ZeroLatency(LatencyModel):
    """No delay (default)."""

    def bars_delay(self) -> int:
        return 0


class RandomLatency(LatencyModel):
    """Random delay drawn from exponential distribution, bounded by ``min_bars`` and ``max_bars``.

    Seeded for reproducibility.
    """

    def __init__(
        self,
        min_bars: int = 0,
        max_bars: int = 5,
        seed: int | None = None,
    ):
        self.min_bars = min_bars
        self.max_bars = max_bars
        self._rng = np.random.default_rng(seed)

    def bars_delay(self) -> int:
        # Exponential with mean = (max - min) / 2, then clamp
        mean = max((self.max_bars - self.min_bars) / 2, 1)
        delay = int(self._rng.exponential(mean))
        return max(self.min_bars, min(delay, self.max_bars))
