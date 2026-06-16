"""Correlation-based risk check for multi-symbol trading."""
import numpy as np
import pandas as pd

from cryptoquant.data.cache import DataCache


class CorrelationCheck:
    """Checks correlation between candidate symbol and existing positions.

    Prevents entering highly correlated symbols to reduce concentration risk.
    """

    def __init__(
        self,
        cache: DataCache,
        threshold: float = 0.7,
        lookback: int = 100,
        exchange: str = "okx",
        timeframe: str = "1h",
    ):
        self.cache = cache
        self.threshold = threshold
        self.lookback = lookback
        self.exchange = exchange
        self.timeframe = timeframe

    def should_enter(
        self, candidate_symbol: str, existing_symbols: list[str]
    ) -> tuple[bool, str]:
        """Check if candidate symbol is allowed given existing positions.

        Returns:
            (allowed, reason)
        """
        if not existing_symbols:
            return True, "no existing positions"

        for existing in existing_symbols:
            corr = self.compute_correlation(candidate_symbol, existing)
            if corr > self.threshold:
                return (
                    False,
                    f"correlation {corr:.2f} > {self.threshold} with {existing}",
                )

        return True, "correlation check passed"

    def compute_correlation(self, symbol_a: str, symbol_b: str) -> float:
        """Compute Pearson correlation between two symbols' returns.

        Returns:
            Correlation coefficient (-1.0 to 1.0). Returns 0.0 on insufficient data.
        """
        df_a = self.cache.get_ohlcv(
            self.exchange, symbol_a, self.timeframe, lookback=self.lookback
        )
        df_b = self.cache.get_ohlcv(
            self.exchange, symbol_b, self.timeframe, lookback=self.lookback
        )

        if df_a.empty or df_b.empty:
            return 0.0

        if len(df_a) < self.lookback or len(df_b) < self.lookback:
            return 0.0

        returns_a = df_a["close"].pct_change().dropna()
        returns_b = df_b["close"].pct_change().dropna()

        min_len = min(len(returns_a), len(returns_b))
        if min_len < 2:
            return 0.0

        returns_a = returns_a.iloc[-min_len:]
        returns_b = returns_b.iloc[-min_len:]

        if returns_a.std() == 0 or returns_b.std() == 0:
            return 0.0

        corr = np.corrcoef(returns_a.values, returns_b.values)[0, 1]
        if not np.isfinite(corr):
            return 0.0

        return float(corr)
