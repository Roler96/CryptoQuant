"""Data validation module for CryptoQuant platform.

Provides data integrity checks for OHLCV time-series data:
- Missing timestamp detection
- Price anomaly detection (unrealistic jumps)
- Volume validation (non-negative values)
- Validation report generation with auto-repair for minor issues
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import structlog

from data.storage import load_historical_data

logger = structlog.get_logger(__name__)

# Validation status constants
VALIDATION_PASS = "PASS"
VALIDATION_WARN = "WARN"
VALIDATION_FAIL = "FAIL"

# Default thresholds
DEFAULT_PRICE_ANOMALY_THRESHOLD = 0.20  # 20% price change
DEFAULT_GAP_THRESHOLD_MS = 1.1  # Allow 10% tolerance on expected interval


@dataclass
class ValidationIssue:
    """Single validation issue.

    Attributes:
        issue_type: Type of issue (missing_timestamp, price_anomaly, volume_issue)
        severity: Severity level (ERROR, WARNING)
        message: Human-readable description
        timestamp: Affected timestamp (if applicable)
        details: Additional context dictionary
    """
    issue_type: str
    severity: str
    message: str
    timestamp: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Complete validation report.

    Attributes:
        status: Overall status (PASS, WARN, FAIL)
        pair: Trading pair validated
        timeframe: Timeframe validated
        total_rows: Total number of data rows
        issues: List of validation issues found
        missing_timestamps: Count of missing timestamps
        price_anomalies: Count of price anomalies
        volume_issues: Count of volume issues
        start_timestamp: First timestamp in data
        end_timestamp: Last timestamp in data
        data_gaps_ms: List of gap durations in milliseconds
    """
    status: str
    pair: str
    timeframe: str
    total_rows: int
    issues: List[ValidationIssue] = field(default_factory=list)
    missing_timestamps: int = 0
    price_anomalies: int = 0
    volume_issues: int = 0
    start_timestamp: Optional[int] = None
    end_timestamp: Optional[int] = None
    data_gaps_ms: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary format."""
        return {
            "status": self.status,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "total_rows": self.total_rows,
            "missing_timestamps": self.missing_timestamps,
            "price_anomalies": self.price_anomalies,
            "volume_issues": self.volume_issues,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "data_gaps_ms": self.data_gaps_ms,
            "issues_count": len(self.issues),
            "issues": [
                {
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "message": i.message,
                    "timestamp": i.timestamp,
                    "details": i.details,
                }
                for i in self.issues
            ],
        }


def _timeframe_to_ms(timeframe: str) -> int:
    """Convert timeframe string to milliseconds.

    Args:
        timeframe: Timeframe string (e.g., "1m", "5m", "1h", "1d")

    Returns:
        Duration in milliseconds

    Raises:
        ValueError: If timeframe format is invalid
    """
    if not timeframe:
        raise ValueError("Timeframe cannot be empty")

    unit = timeframe[-1].lower()
    try:
        value = int(timeframe[:-1])
    except ValueError:
        raise ValueError(f"Invalid timeframe format: {timeframe}")

    if unit == "m":
        return value * 60 * 1000
    elif unit == "h":
        return value * 60 * 60 * 1000
    elif unit == "d":
        return value * 24 * 60 * 60 * 1000
    elif unit == "w":
        return value * 7 * 24 * 60 * 60 * 1000
    else:
        raise ValueError(f"Unsupported timeframe unit: {unit}")


def check_missing_timestamps(
    df: pd.DataFrame,
    timeframe: str,
    tolerance: float = DEFAULT_GAP_THRESHOLD_MS,
) -> Tuple[List[int], List[int]]:
    """Detect gaps in time-series data.

    Args:
        df: DataFrame with 'timestamp' column (sorted ascending)
        timeframe: Expected interval between timestamps
        tolerance: Multiplier for expected interval (default 1.1 = 10% tolerance)

    Returns:
        Tuple of (missing_timestamps_list, gap_durations_ms)
        - missing_timestamps_list: List of specific missing timestamps
        - gap_durations_ms: List of gap durations in milliseconds
    """
    if df.empty or len(df) < 2:
        return [], []

    expected_interval_ms = _timeframe_to_ms(timeframe)
    max_allowed_gap = int(expected_interval_ms * tolerance)

    timestamps = df["timestamp"].values
    missing_timestamps = []
    gap_durations = []

    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]

        if gap > max_allowed_gap:
            # Calculate how many timestamps are missing
            expected_timestamps = int(gap / expected_interval_ms)
            gap_durations.append(int(gap))

            # Generate the specific missing timestamps
            for j in range(1, expected_timestamps):
                missing_ts = timestamps[i - 1] + (j * expected_interval_ms)
                if missing_ts < timestamps[i]:
                    missing_timestamps.append(int(missing_ts))

    logger.debug(
        "missing_timestamps_check",
        total_rows=len(df),
        expected_interval_ms=expected_interval_ms,
        gaps_found=len(gap_durations),
        missing_count=len(missing_timestamps),
    )

    return missing_timestamps, gap_durations


def check_price_anomalies(
    df: pd.DataFrame,
    threshold: float = DEFAULT_PRICE_ANOMALY_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Detect unrealistic price jumps in single bars.

    Args:
        df: DataFrame with OHLCV columns
        threshold: Maximum allowed price change percentage (default 20%)

    Returns:
        List of anomaly dictionaries with:
        - timestamp: Affected timestamp
        - change_pct: Price change percentage
        - open_price: Opening price
        - close_price: Closing price
        - high_price: Highest price
        - low_price: Lowest price
    """
    if df.empty or len(df) < 2:
        return []

    anomalies = []

    # Calculate price changes within each bar
    # Check open to close change
    df_copy = df.copy()
    df_copy["open_to_close_pct"] = (
        (df_copy["close"] - df_copy["open"]) / df_copy["open"]
    ).abs()

    # Check high to low range as percentage of open
    df_copy["hl_range_pct"] = (
        (df_copy["high"] - df_copy["low"]) / df_copy["open"]
    )

    # Check for anomalous bars
    for idx, row in df_copy.iterrows():
        issues = []

        # Open to close change exceeds threshold
        if row["open_to_close_pct"] > threshold:
            issues.append({
                "type": "open_to_close",
                "change_pct": float(row["open_to_close_pct"]),
            })

        # High to low range exceeds 2x threshold (indicates extreme volatility)
        if row["hl_range_pct"] > (threshold * 2):
            issues.append({
                "type": "high_low_range",
                "range_pct": float(row["hl_range_pct"]),
            })

        if issues:
            anomalies.append({
                "timestamp": int(row["timestamp"]),
                "open_price": float(row["open"]),
                "close_price": float(row["close"]),
                "high_price": float(row["high"]),
                "low_price": float(row["low"]),
                "issues": issues,
            })

    logger.debug(
        "price_anomaly_check",
        total_rows=len(df),
        threshold=threshold,
        anomalies_found=len(anomalies),
    )

    return anomalies


def check_volume_validation(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Validate volume data (non-negative, reasonable values).

    Args:
        df: DataFrame with 'volume' column

    Returns:
        List of volume issue dictionaries with:
        - timestamp: Affected timestamp
        - issue_type: Type of volume issue
        - volume: The problematic volume value
        - message: Description of the issue
    """
    if df.empty:
        return []

    issues = []

    # Check for negative volumes
    negative_mask = df["volume"] < 0
    negative_volumes = df[negative_mask]

    for _, row in negative_volumes.iterrows():
        issues.append({
            "timestamp": int(row["timestamp"]),
            "issue_type": "negative_volume",
            "volume": float(row["volume"]),
            "message": f"Negative volume detected: {row['volume']}",
        })

    # Check for zero volumes (warning, not error)
    zero_mask = df["volume"] == 0
    zero_volumes = df[zero_mask]

    for _, row in zero_volumes.iterrows():
        issues.append({
            "timestamp": int(row["timestamp"]),
            "issue_type": "zero_volume",
            "volume": 0.0,
            "message": "Zero volume detected",
        })

    # Check for NaN/Inf volumes
    nan_mask = df["volume"].isna()
    nan_volumes = df[nan_mask]

    for _, row in nan_volumes.iterrows():
        issues.append({
            "timestamp": int(row["timestamp"]),
            "issue_type": "invalid_volume",
            "volume": None,
            "message": "Invalid volume (NaN or Inf) detected",
        })

    logger.debug(
        "volume_validation_check",
        total_rows=len(df),
        negative_count=len(negative_volumes),
        zero_count=len(zero_volumes),
        nan_count=len(nan_volumes),
    )

    return issues


def validate_ohlcv_data(
    df: pd.DataFrame,
    pair: str,
    timeframe: str,
    price_threshold: float = DEFAULT_PRICE_ANOMALY_THRESHOLD,
) -> ValidationReport:
    """Main validation function for OHLCV data.

    Performs comprehensive validation:
    - Checks for missing timestamps
    - Detects price anomalies
    - Validates volume data

    Args:
        df: DataFrame with OHLCV columns
        pair: Trading pair symbol
        timeframe: Candle timeframe
        price_threshold: Maximum allowed price change percentage

    Returns:
        ValidationReport with status and all issues found
    """
    logger.info(
        "starting_ohlcv_validation",
        pair=pair,
        timeframe=timeframe,
        rows=len(df),
    )

    issues = []

    # Initialize report
    report = ValidationReport(
        status=VALIDATION_PASS,
        pair=pair,
        timeframe=timeframe,
        total_rows=len(df),
        start_timestamp=int(df["timestamp"].min()) if not df.empty else None,
        end_timestamp=int(df["timestamp"].max()) if not df.empty else None,
    )

    if df.empty:
        report.status = VALIDATION_FAIL
        issues.append(ValidationIssue(
            issue_type="empty_data",
            severity="ERROR",
            message="DataFrame is empty",
        ))
        report.issues = issues
        return report

    # Check required columns
    required_columns = ["timestamp", "open", "high", "low", "close", "volume"]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        report.status = VALIDATION_FAIL
        issues.append(ValidationIssue(
            issue_type="missing_columns",
            severity="ERROR",
            message=f"Missing required columns: {missing_columns}",
        ))
        report.issues = issues
        return report

    # Check for missing timestamps
    missing_timestamps, gap_durations = check_missing_timestamps(df, timeframe)
    report.missing_timestamps = len(missing_timestamps)
    report.data_gaps_ms = gap_durations

    if missing_timestamps:
        # Determine severity based on gap size
        max_gap_ratio = max(gap_durations) / _timeframe_to_ms(timeframe) if gap_durations else 0

        if max_gap_ratio > 10:  # Gap > 10 intervals
            severity = "ERROR"
            report.status = VALIDATION_FAIL
        elif max_gap_ratio > 3:  # Gap > 3 intervals
            severity = "WARNING"
            if report.status == VALIDATION_PASS:
                report.status = VALIDATION_WARN
        else:
            severity = "INFO"

        for ts in missing_timestamps[:10]:  # Limit to first 10 for brevity
            issues.append(ValidationIssue(
                issue_type="missing_timestamp",
                severity=severity,
                message=f"Missing timestamp at {ts}",
                timestamp=ts,
                details={"gap_ratio": max_gap_ratio},
            ))

        if len(missing_timestamps) > 10:
            issues.append(ValidationIssue(
                issue_type="missing_timestamp",
                severity=severity,
                message=f"... and {len(missing_timestamps) - 10} more missing timestamps",
                details={"total_missing": len(missing_timestamps)},
            ))

    # Check for price anomalies
    price_anomalies = check_price_anomalies(df, price_threshold)
    report.price_anomalies = len(price_anomalies)

    if price_anomalies:
        for anomaly in price_anomalies[:10]:  # Limit to first 10
            issues.append(ValidationIssue(
                issue_type="price_anomaly",
                severity="WARNING",
                message=f"Price anomaly: {anomaly['issues']}",
                timestamp=anomaly["timestamp"],
                details=anomaly,
            ))

        if len(price_anomalies) > 10:
            issues.append(ValidationIssue(
                issue_type="price_anomaly",
                severity="WARNING",
                message=f"... and {len(price_anomalies) - 10} more price anomalies",
                details={"total_anomalies": len(price_anomalies)},
            ))

        if report.status == VALIDATION_PASS:
            report.status = VALIDATION_WARN

    # Check volume validation
    volume_issues = check_volume_validation(df)
    # Count only errors (negative/invalid), not warnings (zero volume)
    report.volume_issues = len([v for v in volume_issues if v["issue_type"] != "zero_volume"])

    for issue in volume_issues:
        if issue["issue_type"] == "negative_volume":
            issues.append(ValidationIssue(
                issue_type="volume_issue",
                severity="ERROR",
                message=issue["message"],
                timestamp=issue["timestamp"],
                details=issue,
            ))
            report.status = VALIDATION_FAIL
        elif issue["issue_type"] == "zero_volume":
            issues.append(ValidationIssue(
                issue_type="volume_issue",
                severity="WARNING",
                message=issue["message"],
                timestamp=issue["timestamp"],
                details=issue,
            ))
            if report.status == VALIDATION_PASS:
                report.status = VALIDATION_WARN
        else:  # invalid_volume
            issues.append(ValidationIssue(
                issue_type="volume_issue",
                severity="ERROR",
                message=issue["message"],
                timestamp=issue["timestamp"],
                details=issue,
            ))
            report.status = VALIDATION_FAIL

    report.issues = issues

    logger.info(
        "ohlcv_validation_complete",
        pair=pair,
        timeframe=timeframe,
        status=report.status,
        total_rows=report.total_rows,
        missing_timestamps=report.missing_timestamps,
        price_anomalies=report.price_anomalies,
        volume_issues=report.volume_issues,
        issues_count=len(issues),
    )

    return report


def validate_data_file(
    pair: str,
    timeframe: str,
    data_dir: Optional[Path] = None,
    price_threshold: float = DEFAULT_PRICE_ANOMALY_THRESHOLD,
) -> Dict[str, Any]:
    """Validate entire Parquet file and return report dictionary.

    Args:
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "1d")
        data_dir: Optional custom data directory
        price_threshold: Maximum allowed price change percentage

    Returns:
        Validation report as dictionary

    Raises:
        FileNotFoundError: If the Parquet file doesn't exist
    """
    logger.info(
        "validating_data_file",
        pair=pair,
        timeframe=timeframe,
        data_dir=str(data_dir) if data_dir else None,
    )

    # Load the data
    df = load_historical_data(pair, timeframe, data_dir)

    # Run validation
    report = validate_ohlcv_data(df, pair, timeframe, price_threshold)

    return report.to_dict()


def auto_repair_data(
    df: pd.DataFrame,
    pair: str,
    timeframe: str,
    fill_missing: bool = True,
    flag_anomalies: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Auto-repair helper for minor data issues.

    Repairs:
    - Fills missing timestamps with NaN rows
    - Adds anomaly flag column for price anomalies

    Args:
        df: DataFrame with OHLCV columns
        pair: Trading pair symbol
        timeframe: Candle timeframe
        fill_missing: Whether to fill missing timestamps
        flag_anomalies: Whether to add anomaly flag column

    Returns:
        Tuple of (repaired_df, repair_report)
    """
    logger.info(
        "starting_auto_repair",
        pair=pair,
        timeframe=timeframe,
        rows=len(df),
        fill_missing=fill_missing,
        flag_anomalies=flag_anomalies,
    )

    repair_report = {
        "original_rows": len(df),
        "filled_timestamps": 0,
        "anomalies_flagged": 0,
        "actions": [],
    }

    if df.empty:
        return df, repair_report

    repaired_df = df.copy()

    # Fill missing timestamps
    if fill_missing:
        missing_timestamps, _ = check_missing_timestamps(df, timeframe)

        if missing_timestamps:
            # Create rows for missing timestamps with NaN values
            missing_data = {
                "timestamp": missing_timestamps,
                "open": [float("nan")] * len(missing_timestamps),
                "high": [float("nan")] * len(missing_timestamps),
                "low": [float("nan")] * len(missing_timestamps),
                "close": [float("nan")] * len(missing_timestamps),
                "volume": [float("nan")] * len(missing_timestamps),
            }
            missing_df = pd.DataFrame(missing_data)

            # Combine and sort
            repaired_df = pd.concat([repaired_df, missing_df], ignore_index=True)
            repaired_df = repaired_df.sort_values("timestamp").reset_index(drop=True)

            repair_report["filled_timestamps"] = len(missing_timestamps)
            repair_report["actions"].append(f"Filled {len(missing_timestamps)} missing timestamps with NaN")

            logger.info(
                "filled_missing_timestamps",
                count=len(missing_timestamps),
                new_total=len(repaired_df),
            )

    # Flag anomalies
    if flag_anomalies:
        anomalies = check_price_anomalies(df)

        if anomalies:
            # Create anomaly flag column (default 0)
            repaired_df["anomaly_flag"] = 0

            # Mark anomalous rows
            anomaly_timestamps = {a["timestamp"] for a in anomalies}
            repaired_df.loc[
                repaired_df["timestamp"].isin(anomaly_timestamps), "anomaly_flag"
            ] = 1

            repair_report["anomalies_flagged"] = len(anomalies)
            repair_report["actions"].append(f"Flagged {len(anomalies)} price anomalies")

            logger.info(
                "flagged_price_anomalies",
                count=len(anomalies),
            )

    repair_report["final_rows"] = len(repaired_df)

    logger.info(
        "auto_repair_complete",
        pair=pair,
        timeframe=timeframe,
        original_rows=repair_report["original_rows"],
        final_rows=repair_report["final_rows"],
        actions=repair_report["actions"],
    )

    return repaired_df, repair_report
