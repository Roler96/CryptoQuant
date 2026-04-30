"""Structured logging setup for CryptoQuant platform.

Provides JSON-formatted logging with sensitive data filtering,
rotating file handlers, and console output.
"""

import logging
import logging.handlers
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from structlog.types import WrappedLogger


# Sensitive data patterns to filter from logs
SENSITIVE_PATTERNS = [
    (re.compile(r'(api[_-]?key[=:]\s*)[\w-]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(api[_-]?secret[=:]\s*)[\w-]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(passphrase[=:]\s*)[\w-]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(password[=:]\s*)[^\s,}]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(token[=:]\s*)[\w-]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(secret[=:]\s*)[\w-]+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(key[=:]\s*)[a-zA-Z0-9]{20,}', re.IGNORECASE), r'\1***REDACTED***'),
]


class SensitiveDataFilter(logging.Filter):
    """Filter that redacts sensitive data from log messages.

    Scans log messages and masks API keys, secrets, passwords,
    and other sensitive credentials.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record to redact sensitive data.

        Args:
            record: LogRecord to filter

        Returns:
            True to allow the record through
        """
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        if hasattr(record, 'args') and record.args:
            record.args = self._redact_args(record.args)

        return True

    def _redact(self, text: str) -> str:
        """Redact sensitive patterns from text.

        Args:
            text: Text to redact

        Returns:
            Redacted text
        """
        for pattern, replacement in SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def _redact_args(self, args: Any) -> Any:
        """Redact sensitive patterns from log args.

        Args:
            args: Arguments to process

        Returns:
            Redacted arguments
        """
        if isinstance(args, tuple):
            return tuple(self._redact(str(arg)) if isinstance(arg, str) else arg for arg in args)
        elif isinstance(args, dict):
            return {k: self._redact(str(v)) if isinstance(v, str) else v for k, v in args.items()}
        return args


class SensitiveDataProcessor:
    """Structlog processor to redact sensitive data from event dicts.

    Processes structlog event dictionaries to mask sensitive information
    in both the event message and bound variables.
    """

    def __call__(
        self,
        logger: WrappedLogger,
        method_name: str,
        event_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process event dict to redact sensitive data.

        Args:
            logger: Logger instance
            method_name: Logging method name
            event_dict: Event dictionary to process

        Returns:
            Processed event dictionary
        """
        # Redact event message
        if 'event' in event_dict and isinstance(event_dict['event'], str):
            event_dict['event'] = self._redact(event_dict['event'])

        # Redact bound variables that might contain sensitive data
        sensitive_keys = {
            'api_key', 'api_secret', 'apiKey', 'apiSecret',
            'passphrase', 'password', 'token', 'secret', 'key'
        }

        for key in event_dict:
            if key in sensitive_keys and isinstance(event_dict[key], str):
                event_dict[key] = '***REDACTED***'
            elif isinstance(event_dict[key], str):
                event_dict[key] = self._redact(event_dict[key])

        return event_dict

    def _redact(self, text: str) -> str:
        """Redact sensitive patterns from text.

        Args:
            text: Text to redact

        Returns:
            Redacted text
        """
        for pattern, replacement in SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


def get_log_directory() -> Path:
    """Get the log directory path.

    Returns:
        Path to log directory, creating it if needed
    """
    log_dir = Path(__file__).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def configure_logging(
    log_level: str = "INFO",
    log_to_file: bool = True,
    log_path: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """Configure structlog with JSON formatting and rotating file handler.

    Sets up structured logging with:
    - JSON output format for machine readability
    - RotatingFileHandler (10MB max, 5 backups by default)
    - Console output for development
    - Sensitive data filtering
    - Timestamp and log level inclusion

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_to_file: Whether to write logs to file
        log_path: Path to log file (defaults to logs/app.log)
        max_bytes: Maximum file size before rotation (default 10MB)
        backup_count: Number of backup files to keep (default 5)
    """
    log_dir = get_log_directory()

    if log_path is None:
        log_path = str(log_dir / "app.log")

    # Timestamps in ISO format
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    # Structlog processors chain
    structlog_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.dict_tracebacks,
        timestamper,
        SensitiveDataProcessor(),  # Filter sensitive data
        structlog.processors.JSONRenderer(),  # JSON output
    ]

    # Configure structlog
    structlog.configure(
        processors=structlog_processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_to_file:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
        )
        file_handler.addFilter(SensitiveDataFilter())
        handlers.append(file_handler)

    # Add sensitive data filter to console handler too
    for handler in handlers:
        handler.addFilter(SensitiveDataFilter())

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
        handlers=handlers,
    )

    # Configure structlog to work with standard logging
    structlog.configure(
        processors=structlog_processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Returns a structlog logger configured with JSON formatting
    and sensitive data filtering. The logger can be bound with
    context variables for structured logging.

    Args:
        name: Logger name (typically __name__ of calling module)

    Returns:
        Configured structlog BoundLogger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("trade_executed", symbol="BTC/USDT", size=0.1)
        {"event": "trade_executed", "symbol": "BTC/USDT", "size": 0.1, ...}
    """
    return structlog.get_logger(name)


def get_bound_logger(**context: Any) -> structlog.stdlib.BoundLogger:
    """Get a logger with pre-bound context variables.

    Creates a logger with context variables that will be included
    in every log message. Useful for adding request IDs, module
    names, or other contextual data.

    Args:
        **context: Context variables to bind to the logger

    Returns:
        BoundLogger with context variables attached

    Example:
        >>> logger = get_bound_logger(request_id="abc123", user="trader1")
        >>> logger.info("order_placed")
        {"event": "order_placed", "request_id": "abc123", "user": "trader1", ...}
    """
    return structlog.get_logger().bind(**context)


# Module-level logger for internal use
_logger: Optional[structlog.stdlib.BoundLogger] = None


def _get_internal_logger() -> structlog.stdlib.BoundLogger:
    """Get internal logger for the logging module itself."""
    global _logger
    if _logger is None:
        _logger = get_logger(__name__)
    return _logger
