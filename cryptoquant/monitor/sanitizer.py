"""Log sanitization — redact sensitive information."""
import re

_SENSITIVE_PATTERNS = [
    (re.compile(r"(api[_-]?key['\":\s=]+)([A-Za-z0-9]{8,})"), r"\1***REDACTED***"),
    (re.compile(r"(secret['\":\s=]+)([A-Za-z0-9]{8,})"), r"\1***REDACTED***"),
    (re.compile(r"(password['\":\s=]+)(\S+)"), r"\1***REDACTED***"),
    (re.compile(r"(passphrase['\":\s=]+)(\S+)"), r"\1***REDACTED***"),
]


def sanitize(message: str) -> str:
    """Redact sensitive information from log messages."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class SanitizingLogger:
    """Logger wrapper that sanitizes messages before logging."""

    def __init__(self, base_logger):
        self._logger = base_logger

    def __getattr__(self, name):
        attr = getattr(self._logger, name)
        if callable(attr) and name in ("debug", "info", "warning", "error", "critical"):

            def wrapper(message, *args, **kwargs):
                if isinstance(message, str):
                    message = sanitize(message)
                return attr(message, *args, **kwargs)

            return wrapper
        return attr
