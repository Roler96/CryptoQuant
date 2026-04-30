"""Logging and audit module for CryptoQuant platform.

Provides structured JSON logging with sensitive data filtering
and immutable audit trails for trades and risk events.
"""

from logs.audit import (
    AuditRecord,
    RiskEventRecord,
    TradeRecord,
    audit_query,
    audit_replay,
    audit_risk_event,
    audit_trade,
    export_audit_to_csv,
)
from logs.logger import (
    SensitiveDataFilter,
    SensitiveDataProcessor,
    configure_logging,
    get_bound_logger,
    get_logger,
)

__all__ = [
    # Logger exports
    "configure_logging",
    "get_logger",
    "get_bound_logger",
    "SensitiveDataFilter",
    "SensitiveDataProcessor",
    # Audit exports
    "audit_trade",
    "audit_risk_event",
    "audit_query",
    "export_audit_to_csv",
    "audit_replay",
    # Record types
    "AuditRecord",
    "TradeRecord",
    "RiskEventRecord",
]
