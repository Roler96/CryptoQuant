"""Alert handler for critical/error log events via webhooks.

Supports rate limiting, deduplication, and batching.
"""

import json
import time
import urllib.request
from typing import Any

from loguru import logger


class AlertHandler:
    """Loguru sink that fires webhooks on configured alert levels.

    Implements the loguru sink interface via __call__.
    Features:
    - Rate limiting: max N alerts per minute
    - Deduplication: suppress repeated identical alerts within cooldown window
    - Timeout: configurable HTTP timeout
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        alert_levels: tuple[str, ...] = ("CRITICAL",),
        timeout: int = 10,
        rate_limit_per_minute: int = 10,
        dedup_window_seconds: int = 300,
    ):
        self.webhook_url = webhook_url
        self.alert_levels = set(alert_levels)
        self.timeout = timeout
        self.rate_limit_per_minute = rate_limit_per_minute
        self.dedup_window_seconds = dedup_window_seconds

        self._sent_timestamps: list[float] = []
        self._recent_messages: dict[str, float] = {}

    def __call__(self, message: Any) -> None:
        """Process a log record and fire webhook if level matches."""
        record = message.record
        level_name = record["level"].name

        if level_name not in self.alert_levels:
            return

        if not self.webhook_url:
            return

        msg_text = str(record["message"])

        # Rate limiting
        if not self._check_rate_limit():
            logger.debug("Alert rate limit exceeded — dropping alert")
            return

        # Deduplication
        if not self._check_dedup(msg_text):
            logger.debug("Alert dedup suppressed — dropping duplicate")
            return

        payload = {
            "level": level_name,
            "message": msg_text,
            "time": record["time"].isoformat(),
            "name": record["name"],
            "function": record["function"],
            "line": record["line"],
        }

        self._send_webhook(payload)

    def _check_rate_limit(self) -> bool:
        """Check if we've exceeded the per-minute rate limit."""
        now = time.time()
        cutoff = now - 60
        self._sent_timestamps = [t for t in self._sent_timestamps if t > cutoff]
        if len(self._sent_timestamps) >= self.rate_limit_per_minute:
            return False
        self._sent_timestamps.append(now)
        return True

    def _check_dedup(self, message: str) -> bool:
        """Check if this message was recently sent (dedup)."""
        now = time.time()
        # Normalize message for dedup (strip whitespace, lowercase first 200 chars)
        normalized = message.strip()[:200].lower()

        # Clean up old entries
        cutoff = now - self.dedup_window_seconds
        self._recent_messages = {
            k: v for k, v in self._recent_messages.items() if v > cutoff
        }

        if normalized in self._recent_messages:
            return False

        self._recent_messages[normalized] = now
        return True

    def _send_webhook(self, payload: dict) -> None:
        """Send alert via webhook."""
        if not self.webhook_url:
            return
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 400:
                    logger.warning(f"Webhook returned status {resp.status}")
        except Exception as e:
            logger.warning(f"Webhook delivery failed: {e}")
