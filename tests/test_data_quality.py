"""Tests for data quality monitoring."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.data.quality import DataQualityChecker, QualityReport


def _make_df(n=50, freq="1h", gaps=None, stale=None, outlier=None, volume_spike=None):
    """Generate OHLCV DataFrame with optional injected anomalies."""
    dates = pd.date_range("2024-01-01", periods=n, freq=freq)
    close = np.linspace(100, 110, n)
    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )

    if gaps:
        for idx in gaps:
            if idx < len(df):
                df.iloc[idx:] = df.iloc[idx:].shift(1)
                df.iloc[idx] = df.iloc[idx - 1]

    if stale:
        for start, length in stale:
            for i in range(start, min(start + length, len(df))):
                df.iloc[i, df.columns.get_loc("close")] = df.iloc[start, df.columns.get_loc("close")]

    if outlier:
        for idx, val in outlier:
            if idx < len(df):
                df.iloc[idx, df.columns.get_loc("close")] = val

    if volume_spike:
        for idx, val in volume_spike:
            if idx < len(df):
                df.iloc[idx, df.columns.get_loc("volume")] = val

    return df


class TestQualityReport:
    def test_dataclass_fields(self):
        report = QualityReport(
            is_healthy=True,
            gap_count=0,
            stale_bars=0,
            outlier_count=0,
            volume_anomaly_count=0,
        )
        assert report.is_healthy is True
        assert report.gap_count == 0


class TestDetectGaps:
    def test_no_gaps(self):
        df = _make_df(50)
        checker = DataQualityChecker(df)
        assert checker.detect_gaps() == []

    def test_detects_gap(self):
        dates = pd.to_datetime(
            ["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 03:00", "2024-01-01 04:00"]
        )
        df = pd.DataFrame(
            {
                "open": [100, 101, 103, 104],
                "high": [101, 102, 104, 105],
                "low": [99, 100, 102, 103],
                "close": [101, 102, 104, 105],
                "volume": [1000, 1000, 1000, 1000],
            },
            index=dates,
        )
        checker = DataQualityChecker(df)
        gaps = checker.detect_gaps()
        assert len(gaps) == 1
        assert "2024-01-01 03:00" in str(gaps[0]["after"])


class TestDetectStale:
    def test_no_stale(self):
        df = _make_df(50)
        checker = DataQualityChecker(df)
        assert checker.detect_stale() == []

    def test_detects_stale(self):
        df = _make_df(50)
        df.loc[df.index[5:10], "close"] = 100.0
        checker = DataQualityChecker(df)
        stale = checker.detect_stale(max_unchanged_bars=3)
        assert len(stale) >= 1
        assert stale[0]["bars"] >= 3


class TestDetectOutliers:
    def test_no_outliers(self):
        df = _make_df(50)
        checker = DataQualityChecker(df)
        assert checker.detect_outliers() == []

    def test_detects_outlier(self):
        df = _make_df(50)
        df.loc[df.index[10], "close"] = 200.0
        checker = DataQualityChecker(df)
        outliers = checker.detect_outliers()
        assert len(outliers) >= 1
        assert outliers[0]["method"] == "zscore"

    def test_iqr_method(self):
        df = _make_df(50)
        df.loc[df.index[10], "close"] = 200.0
        checker = DataQualityChecker(df)
        outliers = checker.detect_outliers(method="iqr")
        assert len(outliers) >= 1


class TestDetectVolumeAnomalies:
    def test_no_anomalies(self):
        df = _make_df(50)
        checker = DataQualityChecker(df)
        assert checker.detect_volume_anomalies() == []

    def test_detects_spike(self):
        df = _make_df(50)
        df.loc[df.index[25], "volume"] = 50000.0
        checker = DataQualityChecker(df)
        anomalies = checker.detect_volume_anomalies()
        assert len(anomalies) >= 1
        assert anomalies[0]["timestamp"] == df.index[25]


class TestCheck:
    def test_healthy_data(self):
        df = _make_df(50)
        checker = DataQualityChecker(df)
        report = checker.check()
        assert isinstance(report, QualityReport)
        assert report.is_healthy is True
        assert report.gap_count == 0
        assert report.stale_bars == 0
        assert report.outlier_count == 0
        assert report.volume_anomaly_count == 0

    def test_unhealthy_data(self):
        dates = pd.to_datetime(
            [
                "2024-01-01 00:00",
                "2024-01-01 01:00",
                "2024-01-01 02:00",
                "2024-01-01 03:00",
                "2024-01-01 04:00",
            ]
        )
        df = pd.DataFrame(
            {
                "open": [100, 100, 100, 100, 103],
                "high": [101, 101, 101, 101, 104],
                "low": [99, 99, 99, 99, 102],
                "close": [100, 100, 100, 100, 103],
                "volume": [1000, 1000, 1000, 1000, 50000],
            },
            index=dates,
        )
        checker = DataQualityChecker(df)
        report = checker.check()
        vol = checker.detect_volume_anomalies(lookback=3)
        report = QualityReport(
            is_healthy=False,
            gap_count=report.gap_count,
            stale_bars=report.stale_bars,
            outlier_count=report.outlier_count,
            volume_anomaly_count=len(vol),
            details={**report.details, "volume_anomalies": vol},
        )
        assert report.is_healthy is False
        assert report.gap_count == 0
        assert report.stale_bars == 1
        assert report.volume_anomaly_count == 1
        assert "stale" in report.details
        assert "volume_anomalies" in report.details
