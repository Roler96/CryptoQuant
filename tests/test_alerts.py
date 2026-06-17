"""Tests for AlertHandler."""
import json
from unittest.mock import MagicMock, patch


from cryptoquant.monitor.alerts import AlertHandler


class TestAlertHandler:
    def test_critical_level_triggers_webhook(self):
        handler = AlertHandler(
            webhook_url="http://example.com/webhook",
            alert_levels=("CRITICAL",),
        )

        mock_message = MagicMock()
        mock_message.record = {
            "level": MagicMock(name="CRITICAL"),
            "message": "System failure",
            "time": MagicMock(isoformat=MagicMock(return_value="2024-01-01T00:00:00")),
            "name": "test",
            "function": "test_func",
            "line": 42,
        }
        mock_message.record["level"].name = "CRITICAL"

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_urlopen.return_value.__enter__ = MagicMock(
                return_value=mock_response
            )
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            handler(mock_message)
            mock_urlopen.assert_called_once()

    def test_non_alert_level_ignored(self):
        handler = AlertHandler(
            webhook_url="http://example.com/webhook",
            alert_levels=("CRITICAL",),
        )

        mock_message = MagicMock()
        mock_message.record = {
            "level": MagicMock(name="INFO"),
            "message": "Info message",
            "time": MagicMock(),
            "name": "test",
            "function": "test_func",
            "line": 42,
        }
        mock_message.record["level"].name = "INFO"

        with patch("urllib.request.urlopen") as mock_urlopen:
            handler(mock_message)
            mock_urlopen.assert_not_called()

    def test_no_webhook_url_skips_send(self):
        handler = AlertHandler(
            webhook_url=None,
            alert_levels=("CRITICAL",),
        )

        mock_message = MagicMock()
        mock_message.record = {
            "level": MagicMock(name="CRITICAL"),
            "message": "System failure",
            "time": MagicMock(),
            "name": "test",
            "function": "test_func",
            "line": 42,
        }
        mock_message.record["level"].name = "CRITICAL"

        with patch("urllib.request.urlopen") as mock_urlopen:
            handler(mock_message)
            mock_urlopen.assert_not_called()

    def test_error_level_included(self):
        handler = AlertHandler(
            webhook_url="http://example.com/webhook",
            alert_levels=("CRITICAL", "ERROR"),
        )

        mock_message = MagicMock()
        mock_message.record = {
            "level": MagicMock(name="ERROR"),
            "message": "Error occurred",
            "time": MagicMock(isoformat=MagicMock(return_value="2024-01-01T00:00:00")),
            "name": "test",
            "function": "test_func",
            "line": 42,
        }
        mock_message.record["level"].name = "ERROR"

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_urlopen.return_value.__enter__ = MagicMock(
                return_value=mock_response
            )
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            handler(mock_message)
            mock_urlopen.assert_called_once()

    def test_webhook_payload_structure(self):
        handler = AlertHandler(
            webhook_url="http://example.com/webhook",
            alert_levels=("CRITICAL",),
        )

        mock_message = MagicMock()
        mock_message.record = {
            "level": MagicMock(name="CRITICAL"),
            "message": "System failure",
            "time": MagicMock(isoformat=MagicMock(return_value="2024-01-01T00:00:00")),
            "name": "test",
            "function": "test_func",
            "line": 42,
        }
        mock_message.record["level"].name = "CRITICAL"

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_urlopen.return_value.__enter__ = MagicMock(
                return_value=mock_response
            )
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            handler(mock_message)

            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            payload = json.loads(req.data)
            assert payload["level"] == "CRITICAL"
            assert payload["message"] == "System failure"
            assert payload["name"] == "test"
            assert payload["function"] == "test_func"
            assert payload["line"] == 42

    def test_webhook_failure_logged(self):
        handler = AlertHandler(
            webhook_url="http://example.com/webhook",
            alert_levels=("CRITICAL",),
        )

        mock_message = MagicMock()
        mock_message.record = {
            "level": MagicMock(name="CRITICAL"),
            "message": "System failure",
            "time": MagicMock(),
            "name": "test",
            "function": "test_func",
            "line": 42,
        }
        mock_message.record["level"].name = "CRITICAL"

        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            with patch("cryptoquant.monitor.alerts.logger") as mock_logger:
                handler(mock_message)
                mock_logger.warning.assert_called_once()

    def test_webhook_4xx_warns(self):
        handler = AlertHandler(
            webhook_url="http://example.com/webhook",
            alert_levels=("CRITICAL",),
        )

        mock_message = MagicMock()
        mock_message.record = {
            "level": MagicMock(name="CRITICAL"),
            "message": "System failure",
            "time": MagicMock(),
            "name": "test",
            "function": "test_func",
            "line": 42,
        }
        mock_message.record["level"].name = "CRITICAL"

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 500
            mock_urlopen.return_value.__enter__ = MagicMock(
                return_value=mock_response
            )
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            with patch("cryptoquant.monitor.alerts.logger") as mock_logger:
                handler(mock_message)
                mock_logger.warning.assert_called_once()


class TestAlertConfig:
    def test_default_config(self):
        from cryptoquant.config import AlertConfig

        config = AlertConfig()
        assert config.webhook_url == ""
        assert config.alert_levels == ("CRITICAL",)

    def test_custom_levels(self):
        from cryptoquant.config import AlertConfig

        config = AlertConfig(alert_levels=("CRITICAL", "ERROR"))
        assert config.alert_levels == ("CRITICAL", "ERROR")
