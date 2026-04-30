"""Audit trail module for CryptoQuant platform.

Provides immutable audit logging for trades, risk events, and other
sensitive operations. Records are stored in JSON format and can be
queried, exported to CSV, and replayed for analysis.
"""

import csv
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from logs.logger import get_logger

logger = get_logger(__name__)


def _get_audit_file_path() -> Path:
    """Get the path to the audit trail JSON file."""
    log_dir = Path(__file__).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "audit_trail.json"


def _serialize_decimal(obj: Any) -> Any:
    """Serialize Decimal to string for JSON serialization."""
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


@dataclass(frozen=True)
class AuditRecord:
    """Base audit record structure.

    Attributes:
        id: Unique identifier for this audit record
        timestamp: ISO format timestamp when record was created
        event_type: Type of event (trade, risk_event, etc.)
        data: Event-specific data as a dictionary
    """
    id: str
    timestamp: str
    event_type: str
    data: Dict[str, Any]


@dataclass(frozen=True)
class TradeRecord:
    """Audit record for a trade execution.

    Attributes:
        trade_id: Unique trade identifier
        strategy: Strategy name that generated the trade
        pair: Trading pair (e.g., "BTC/USDT")
        side: Trade side ("buy", "sell", "long", "short")
        size: Position size
        entry_price: Entry price for the trade
        exit_price: Exit price (if closed)
        timestamp: When the trade was executed
        pnl: Profit/loss (if closed)
        pnl_pct: Profit/loss percentage
        status: Trade status ("open", "closed", "canceled")
    """
    trade_id: str
    strategy: str
    pair: str
    side: str
    size: Decimal
    entry_price: Decimal
    exit_price: Optional[Decimal] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    pnl: Optional[Decimal] = None
    pnl_pct: Optional[Decimal] = None
    status: str = "open"

    def to_audit_record(self) -> AuditRecord:
        """Convert TradeRecord to generic AuditRecord."""
        return AuditRecord(
            id=str(uuid.uuid4()),
            timestamp=self.timestamp,
            event_type="trade",
            data=asdict(self),
        )


@dataclass(frozen=True)
class RiskEventRecord:
    """Audit record for a risk management event.

    Attributes:
        event_id: Unique event identifier
        event_type: Type of risk event (stop_loss, position_limit, drawdown, etc.)
        strategy: Strategy name (if applicable)
        pair: Trading pair (if applicable)
        severity: Event severity ("info", "warning", "critical")
        message: Human-readable description
        timestamp: When the event occurred
        metadata: Additional event data
    """
    event_id: str
    event_type: str
    strategy: Optional[str] = None
    pair: Optional[str] = None
    severity: str = "info"
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_audit_record(self) -> AuditRecord:
        """Convert RiskEventRecord to generic AuditRecord."""
        return AuditRecord(
            id=str(uuid.uuid4()),
            timestamp=self.timestamp,
            event_type="risk_event",
            data=asdict(self),
        )


def audit_trade(
    trade_id: str,
    strategy: str,
    pair: str,
    side: str,
    size: Decimal,
    entry_price: Decimal,
    exit_price: Optional[Decimal] = None,
    pnl: Optional[Decimal] = None,
    pnl_pct: Optional[Decimal] = None,
    status: str = "open",
) -> TradeRecord:
    """Record a trade execution to the audit trail.

    Creates an immutable audit record of a trade and appends it
    to the audit trail JSON file.

    Args:
        trade_id: Unique identifier for the trade
        strategy: Strategy name that executed the trade
        pair: Trading pair symbol (e.g., "BTC/USDT")
        side: Trade side ("buy", "sell", "long", "short")
        size: Position size
        entry_price: Entry price
        exit_price: Exit price (if trade is closed)
        pnl: Profit/loss amount (if closed)
        pnl_pct: Profit/loss percentage (if closed)
        status: Current status ("open", "closed", "canceled")

    Returns:
        TradeRecord that was written to audit trail

    Example:
        >>> audit_trade(
        ...     trade_id="trade_001",
        ...     strategy="trend_following",
        ...     pair="BTC/USDT",
        ...     side="long",
        ...     size=Decimal("0.1"),
        ...     entry_price=Decimal("50000.00"),
        ...     status="open",
        ... )
    """
    record = TradeRecord(
        trade_id=trade_id,
        strategy=strategy,
        pair=pair,
        side=side,
        size=size,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        pnl_pct=pnl_pct,
        status=status,
    )

    audit_record = record.to_audit_record()
    _append_audit_record(audit_record)

    logger.info(
        "audit_trade_recorded",
        trade_id=trade_id,
        strategy=strategy,
        pair=pair,
        side=side,
        status=status,
    )

    return record


def audit_risk_event(
    event_type: str,
    strategy: Optional[str] = None,
    pair: Optional[str] = None,
    severity: str = "info",
    message: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> RiskEventRecord:
    """Record a risk management event to the audit trail.

    Creates an immutable audit record of a risk event such as
    stop loss triggers, position limit breaches, or drawdown alerts.

    Args:
        event_type: Type of risk event (e.g., "stop_loss", "drawdown_alert")
        strategy: Strategy name (if applicable)
        pair: Trading pair (if applicable)
        severity: Event severity level ("info", "warning", "critical")
        message: Human-readable description
        metadata: Additional event data as dictionary

    Returns:
        RiskEventRecord that was written to audit trail

    Example:
        >>> audit_risk_event(
        ...     event_type="stop_loss_triggered",
        ...     strategy="trend_following",
        ...     pair="BTC/USDT",
        ...     severity="warning",
        ...     message="Stop loss triggered at 48500",
        ...     metadata={"stop_price": "48000", "current_price": "47800"},
        ... )
    """
    event_id = f"risk_{uuid.uuid4().hex[:12]}"

    record = RiskEventRecord(
        event_id=event_id,
        event_type=event_type,
        strategy=strategy,
        pair=pair,
        severity=severity,
        message=message,
        metadata=metadata or {},
    )

    audit_record = record.to_audit_record()
    _append_audit_record(audit_record)

    logger.info(
        "audit_risk_event_recorded",
        event_id=event_id,
        event_type=event_type,
        severity=severity,
        strategy=strategy,
        pair=pair,
    )

    return record


def _append_audit_record(record: AuditRecord) -> None:
    """Append an audit record to the JSON file.

    Args:
        record: AuditRecord to append
    """
    audit_file = _get_audit_file_path()

    record_dict = asdict(record)

    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            json_line = json.dumps(record_dict, default=_serialize_decimal)
            f.write(json_line + "\n")
    except Exception as e:
        logger.error("failed_to_write_audit_record", error=str(e), record_id=record.id)
        raise


def _read_audit_records() -> List[AuditRecord]:
    """Read all audit records from the JSON file.

    Returns:
        List of AuditRecord objects
    """
    audit_file = _get_audit_file_path()
    records: List[AuditRecord] = []

    if not audit_file.exists():
        return records

    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    records.append(AuditRecord(
                        id=data["id"],
                        timestamp=data["timestamp"],
                        event_type=data["event_type"],
                        data=data["data"],
                    ))
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("failed_to_parse_audit_record", error=str(e), line=line[:100])
                    continue
    except Exception as e:
        logger.error("failed_to_read_audit_file", error=str(e))
        raise

    return records


def audit_query(
    strategy: Optional[str] = None,
    pair: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query audit records with optional filters.

    Filters the audit trail by strategy, trading pair, date range,
    or event type. Returns matching records in chronological order.

    Args:
        strategy: Filter by strategy name
        pair: Filter by trading pair
        start_date: Start date in ISO format (e.g., "2024-01-01")
        end_date: End date in ISO format (e.g., "2024-12-31")
        event_type: Filter by event type ("trade", "risk_event")

    Returns:
        List of matching audit record dictionaries

    Example:
        >>> results = audit_query(
        ...     strategy="trend_following",
        ...     pair="BTC/USDT",
        ...     start_date="2024-01-01",
        ...     event_type="trade",
        ... )
    """
    records = _read_audit_records()
    results: List[Dict[str, Any]] = []

    for record in records:
        # Filter by event type
        if event_type and record.event_type != event_type:
            continue

        # Filter by date range
        if start_date and record.timestamp < start_date:
            continue
        if end_date and record.timestamp > end_date:
            continue

        # Filter by strategy (in data for trade/risk records)
        if strategy:
            record_strategy = record.data.get("strategy")
            if record_strategy != strategy:
                continue

        # Filter by pair
        if pair:
            record_pair = record.data.get("pair")
            if record_pair != pair:
                continue

        results.append({
            "id": record.id,
            "timestamp": record.timestamp,
            "event_type": record.event_type,
            "data": record.data,
        })

    logger.info(
        "audit_query_executed",
        filters={
            "strategy": strategy,
            "pair": pair,
            "start_date": start_date,
            "end_date": end_date,
            "event_type": event_type,
        },
        results_count=len(results),
    )

    return results


def export_audit_to_csv(output_path: Optional[str] = None) -> str:
    """Export all audit records to a CSV file.

    Converts the JSON audit trail to CSV format for easier
    analysis in spreadsheet applications.

    Args:
        output_path: Path for output CSV file (defaults to logs/audit_export.csv)

    Returns:
        Path to the exported CSV file

    Example:
        >>> csv_path = export_audit_to_csv("/tmp/my_audit.csv")
        >>> print(f"Exported to: {csv_path}")
    """
    if output_path is None:
        log_dir = Path(__file__).parent
        output_path = str(log_dir / "audit_export.csv")

    records = _read_audit_records()

    if not records:
        logger.warning("no_audit_records_to_export")
        return output_path

    # Flatten records for CSV
    flat_records: List[Dict[str, Any]] = []
    for record in records:
        flat_record: Dict[str, Any] = {
            "id": record.id,
            "timestamp": record.timestamp,
            "event_type": record.event_type,
        }
        # Add all data fields with prefix
        for key, value in record.data.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat_record[f"data_{key}_{sub_key}"] = sub_value
            else:
                flat_record[f"data_{key}"] = value
        flat_records.append(flat_record)

    # Get all fieldnames
    fieldnames = set()
    for record in flat_records:
        fieldnames.update(record.keys())
    fieldnames = sorted(fieldnames)

    try:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat_records)
    except Exception as e:
        logger.error("failed_to_export_audit_csv", error=str(e), output_path=output_path)
        raise

    logger.info("audit_exported_to_csv", output_path=output_path, record_count=len(records))

    return output_path


def audit_replay(
    strategy: Optional[str] = None,
    pair: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Iterator[Union[TradeRecord, RiskEventRecord]]:
    """Replay audit events as record objects.

    Yields TradeRecord and RiskEventRecord objects for replaying
    historical trades and risk events. Useful for backtesting
    audit data or reconstructing trading history.

    Args:
        strategy: Filter by strategy name
        pair: Filter by trading pair
        start_date: Start date in ISO format
        end_date: End date in ISO format

    Yields:
        TradeRecord or RiskEventRecord objects

    Example:
        >>> for record in audit_replay(strategy="trend_following"):
        ...     if isinstance(record, TradeRecord):
        ...         print(f"Trade: {record.trade_id} PnL: {record.pnl}")
        ...     elif isinstance(record, RiskEventRecord):
        ...         print(f"Risk Event: {record.event_type}")
    """
    records = _read_audit_records()

    for record in records:
        # Apply filters
        if start_date and record.timestamp < start_date:
            continue
        if end_date and record.timestamp > end_date:
            continue

        if strategy:
            record_strategy = record.data.get("strategy")
            if record_strategy != strategy:
                continue

        if pair:
            record_pair = record.data.get("pair")
            if record_pair != pair:
                continue

        # Convert to appropriate record type
        if record.event_type == "trade":
            yield TradeRecord(
                trade_id=record.data.get("trade_id", ""),
                strategy=record.data.get("strategy", ""),
                pair=record.data.get("pair", ""),
                side=record.data.get("side", ""),
                size=Decimal(str(record.data.get("size", 0))),
                entry_price=Decimal(str(record.data.get("entry_price", 0))),
                exit_price=Decimal(str(record.data.get("exit_price"))) if record.data.get("exit_price") else None,
                timestamp=record.data.get("timestamp", record.timestamp),
                pnl=Decimal(str(record.data.get("pnl"))) if record.data.get("pnl") else None,
                pnl_pct=Decimal(str(record.data.get("pnl_pct"))) if record.data.get("pnl_pct") else None,
                status=record.data.get("status", "unknown"),
            )
        elif record.event_type == "risk_event":
            yield RiskEventRecord(
                event_id=record.data.get("event_id", ""),
                event_type=record.data.get("event_type", ""),
                strategy=record.data.get("strategy"),
                pair=record.data.get("pair"),
                severity=record.data.get("severity", "info"),
                message=record.data.get("message", ""),
                timestamp=record.data.get("timestamp", record.timestamp),
                metadata=record.data.get("metadata", {}),
            )

    logger.info(
        "audit_replay_completed",
        filters={
            "strategy": strategy,
            "pair": pair,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
