"""Alert handler for critical/error log events via webhooks."""
import json
import urllib.request
from typing import Any

from loguru import logger


class AlertHandler:
    """Loguru sink that fires webhooks on configured alert levels.

    Implements the loguru sink interface via __call__.
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        alert_levels: tuple[str, ...] = ("CRITICAL",),
        timeout: int = 10,
    ):
        self.webhook_url = webhook_url
        self.alert_levels = set(alert_levels)
        self.timeout = timeout
        self._last_alert_ts: float = 0.0

    def __call__(self, message: Any) -> None:
        """Process a log record and fire webhook if level matches."""
        record = message.record
        level_name = record["level"].name

        if level_name not in self.alert_levels:
            return

        if not self.webhook_url:
            return

        payload = {
            "level": level_name,
            "message": record["message"],
            "time": record["time"].isoformat(),
            "name": record["name"],
            "function": record["function"],
            "line": record["line"],
        }

        self._send_webhook(payload)

    def _send_webhook(self, payload: dict) -> None:
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
