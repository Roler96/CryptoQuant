"""Data quality monitoring for OHLCV data."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class QualityReport:
    """Summary of data quality checks.

    is_healthy: True when there are no data integrity issues
    (gaps, stale bars).  Market anomalies (outliers, volume spikes)
    are flagged separately and do NOT make the data unhealthy —
    they are normal in crypto markets.
    """

    is_healthy: bool
    gap_count: int
    stale_bars: int
    outlier_count: int
    volume_anomaly_count: int
    details: dict = field(default_factory=dict)


class DataQualityChecker:
    """Check OHLCV data for quality issues."""

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def check(self) -> QualityReport:
        """Run all quality checks and return a summary report.

        is_healthy is False only when there are data INTEGRITY issues
        (gaps, stale bars). Market anomalies (outliers, volume spikes)
        are reported but do NOT block trading — they are normal crypto
        behaviour.
        """
        gaps = self.detect_gaps()
        stale = self.detect_stale()
        outliers = self.detect_outliers()
        volume = self.detect_volume_anomalies()

        # Only data integrity issues make data unhealthy
        integrity_issues = len(gaps) + len(stale)
        is_healthy = integrity_issues == 0

        return QualityReport(
            is_healthy=is_healthy,
            gap_count=len(gaps),
            stale_bars=len(stale),
            outlier_count=len(outliers),
            volume_anomaly_count=len(volume),
            details={
                "gaps": gaps,
                "stale": stale,
                "outliers": outliers,
                "volume_anomalies": volume,
            },
        )

    def detect_gaps(self, tolerance: float = 1.1) -> list[dict]:
        """Detect timestamp gaps larger than expected interval."""
        if len(self.df) < 2 or not isinstance(self.df.index, pd.DatetimeIndex):
            return []

        diffs = self.df.index.to_series().diff().dropna()
        if len(diffs) == 0:
            return []

        median_diff = diffs.median()
        gap_mask = diffs > median_diff * tolerance
        gaps = []
        for ts, diff in diffs[gap_mask].items():
            gaps.append({
                "after": ts,
                "gap_duration": str(diff),
                "expected": str(median_diff),
            })
        return gaps

    def detect_stale(self, max_unchanged_bars: int = 3) -> list[dict]:
        """Detect consecutive bars with identical close prices."""
        if len(self.df) < 2:
            return []

        close = self.df["close"]
        unchanged = close == close.shift(1)
        stale = []
        count = 0
        start_idx = None

        for i, is_stale in enumerate(unchanged):
            if is_stale:
                if count == 0:
                    start_idx = i
                count += 1
            else:
                if count >= max_unchanged_bars:
                    stale.append({
                        "start": self.df.index[start_idx],
                        "end": self.df.index[i - 1],
                        "bars": count,
                    })
                count = 0
                start_idx = None

        if count >= max_unchanged_bars:
            stale.append({
                "start": self.df.index[start_idx],
                "end": self.df.index[len(unchanged) - 1],
                "bars": count,
            })

        return stale

    def detect_outliers(
        self, method: str = "zscore", threshold: float = 3.0
    ) -> list[dict]:
        """Detect extreme price movements."""
        if len(self.df) < 2:
            return []

        returns = self.df["close"].pct_change().dropna()
        if len(returns) == 0:
            return []

        if method == "zscore":
            z_scores = np.abs((returns - returns.mean()) / returns.std())
            mask = z_scores > threshold
        elif method == "iqr":
            q1 = returns.quantile(0.25)
            q3 = returns.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            mask = (returns < lower) | (returns > upper)
        else:
            return []

        outliers = []
        for ts, ret in returns[mask].items():
            outliers.append({
                "timestamp": ts,
                "return_pct": round(float(ret) * 100, 4),
                "method": method,
            })
        return outliers

    def detect_volume_anomalies(
        self, lookback: int = 20, multiplier: float = 3.0
    ) -> list[dict]:
        """Detect volume spikes above rolling average."""
        if len(self.df) < lookback + 1:
            return []

        volume = self.df["volume"]
        avg_volume = volume.rolling(lookback).mean().shift(1)
        mask = volume > (avg_volume * multiplier)

        anomalies = []
        for ts, vol in volume[mask].items():
            anomalies.append({
                "timestamp": ts,
                "volume": float(vol),
                "avg_volume": round(float(avg_volume.loc[ts]), 2),
                "multiplier": multiplier,
            })
        return anomalies
