"""Correlation-based risk check for multi-symbol trading."""
import numpy as np
import pandas as pd


class CorrelationCheck:
    """Checks correlation between candidate symbol and existing positions.

    Prevents entering highly correlated symbols to reduce concentration risk.
    """

    def __init__(
        self,
        threshold: float = 0.7,
        lookback: int = 100,
    ):
        self.threshold = threshold
        self.lookback = lookback

    def should_enter(
        self, df_candidate: pd.DataFrame, existing_dfs: list[pd.DataFrame]
    ) -> tuple[bool, str]:
        """Check if candidate symbol is allowed given existing positions.

        Returns:
            (allowed, reason)
        """
        if not existing_dfs:
            return True, "no existing positions"

        for existing in existing_dfs:
            corr = self.compute_correlation(df_candidate, existing)
            if corr > self.threshold:
                return (
                    False,
                    f"correlation {corr:.2f} > {self.threshold}",
                )

        return True, "correlation check passed"

    def compute_correlation(
        self, df_a: pd.DataFrame, df_b: pd.DataFrame
    ) -> float:
        """Compute Pearson correlation between two DataFrames' returns.

        Returns:
            Correlation coefficient (-1.0 to 1.0). Returns 0.0 on insufficient data.
        """
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
