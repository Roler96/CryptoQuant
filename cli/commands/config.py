"""Config command handler for CLI.

Provides functionality to view and modify platform configuration settings.
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
import yaml
from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel

logger = structlog.get_logger(__name__)
console = Console()

CONFIG_PATH = Path("config/config.yaml")
DEFAULT_CONFIG_PATH = Path("config/config.yaml.default")


def run_config(args: argparse.Namespace) -> int:
    """Handle configuration commands.

    Args:
        args: Parsed command-line arguments containing:
            - show: Display current configuration
            - set: Set configuration value (key=value)
            - reset: Reset configuration to defaults

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger.info("config_command", show=args.show, set_value=args.set, reset=args.reset)

    try:
        if args.show:
            return _show_config()
        elif args.set:
            return _set_config_value(args.set)
        elif args.reset:
            return _reset_config()
        else:
            console.print("[red]Error: No config action specified[/red]")
            return 1

    except Exception as e:
        logger.error("config_command_failed", error=str(e))
        console.print(f"[red]Error: {e}[/red]")
        return 1


def _show_config() -> int:
    """Display current configuration.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    if not CONFIG_PATH.exists():
        console.print(f"[red]Configuration file not found: {CONFIG_PATH}[/red]")
        return 1

    try:
        with open(CONFIG_PATH, "r") as f:
            content = f.read()

        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="[bold cyan]Current Configuration[/bold cyan]"))

        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)

        console.print()
        console.print("[bold]Quick Overview:[/bold]")

        exchange = config.get("exchange", {})
        console.print(f"  Exchange: {exchange.get('name', 'unknown')} (sandbox: {exchange.get('sandbox', True)})")

        trading = config.get("trading", {})
        symbols = trading.get("symbols", [])
        console.print(f"  Symbols: {', '.join(symbols) if symbols else 'None'}")
        console.print(f"  Timeframe: {trading.get('timeframe', 'unknown')}")

        risk = config.get("risk", {})
        console.print(f"  Max Drawdown: {risk.get('max_drawdown', 0) * 100:.1f}%")

        live = config.get("live", {})
        console.print(f"  Live Trading: {'Enabled' if live.get('enabled', False) else 'Disabled'}")

        return 0

    except Exception as e:
        console.print(f"[red]Error reading configuration: {e}[/red]")
        return 1


def _set_config_value(key_value: str) -> int:
    """Set a configuration value.

    Args:
        key_value: Key-value pair in format "section.key=value" or "section.key=value1,value2"

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    if "=" not in key_value:
        console.print("[red]Error: Invalid format. Use: section.key=value[/red]")
        console.print("[dim]Examples:[/dim]")
        console.print("  config --set risk.max_drawdown=0.20")
        console.print("  config --set trading.timeframe=4h")
        console.print("  config --set trading.symbols=BTC/USDT,ETH/USDT")
        return 1

    key, value = key_value.split("=", 1)
    key = key.strip()
    value = value.strip()

    key_parts = key.split(".")

    if len(key_parts) < 2:
        console.print("[red]Error: Key must be in format 'section.key' (e.g., risk.max_drawdown)[/red]")
        return 1

    if not CONFIG_PATH.exists():
        console.print(f"[red]Configuration file not found: {CONFIG_PATH}[/red]")
        return 1

    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)

        current = config
        for part in key_parts[:-1]:
            if part not in current:
                console.print(f"[red]Error: Section '{part}' not found in configuration[/red]")
                return 1
            current = current[part]

        final_key = key_parts[-1]

        if final_key not in current:
            console.print(f"[yellow]Warning: Key '{final_key}' not found. Creating new key.[/yellow]")

        old_value = current.get(final_key)
        new_value = _parse_value(value, old_value)

        is_valid, error_msg = _validate_config_value(key, new_value)
        if not is_valid:
            console.print(f"[red]Validation failed for {key}: {error_msg}[/red]")
            return 1

        current[final_key] = new_value

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        console.print(f"[green]✓ Updated {key} = {new_value}[/green]")

        if old_value is not None:
            console.print(f"[dim]Previous value: {old_value}[/dim]")

        logger.info("config_value_updated", key=key, old_value=old_value, new_value=new_value)
        return 0

    except Exception as e:
        console.print(f"[red]Error updating configuration: {e}[/red]")
        return 1


def _reset_config() -> int:
    """Reset configuration to defaults.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    if not CONFIG_PATH.exists():
        console.print(f"[yellow]Configuration file not found: {CONFIG_PATH}[/yellow]")
        return 0

    console.print("[yellow]⚠ This will reset all configuration to defaults.[/yellow]")
    confirmation = input("Type 'RESET' to confirm: ")

    if confirmation != "RESET":
        console.print("Reset cancelled.")
        return 0

    try:
        backup_path = Path(f"{CONFIG_PATH}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(CONFIG_PATH, backup_path)
        console.print(f"[dim]Backup created: {backup_path}[/dim]")

        default_config = _create_default_config()

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(default_config, f, default_flow_style=False, sort_keys=False)

        console.print("[green]✓ Configuration reset to defaults[/green]")
        logger.info("config_reset_to_defaults", backup_path=str(backup_path))

        return 0

    except Exception as e:
        console.print(f"[red]Error resetting configuration: {e}[/red]")
        return 1


CONFIG_VALIDATORS: Dict[str, Dict[str, Any]] = {
    "risk.max_daily_loss": {"type": float, "min": 0, "max": 1},
    "risk.max_drawdown": {"type": float, "min": 0, "max": 1},
    "risk.stop_loss_pct": {"type": float, "min": 0, "max": 1},
    "risk.take_profit_pct": {"type": float, "min": 0, "max": 1},
    "risk.max_positions": {"type": int, "min": 1, "max": 100},
    "exchange.sandbox": {"type": bool},
    "exchange.rate_limit": {"type": bool},
    "exchange.enable_rate_limit": {"type": bool},
    "live.enabled": {"type": bool},
    "live.dry_run": {"type": bool},
    "backtest.initial_capital": {"type": int, "min": 100},
    "backtest.commission": {"type": float, "min": 0, "max": 0.5},
    "backtest.slippage": {"type": float, "min": 0, "max": 0.1},
    "data.update_interval": {"type": int, "min": 10, "max": 3600},
    "data.lookback_periods": {"type": int, "min": 10, "max": 10000},
    "logging.level": {"type": str, "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
    "logging.log_to_file": {"type": bool},
    "logging.retention_days": {"type": int, "min": 1, "max": 365},
}


def _validate_config_value(key: str, value: Any) -> Tuple[bool, str]:
    if key not in CONFIG_VALIDATORS:
        return True, ""
    rules = CONFIG_VALIDATORS[key]
    expected_type = rules.get("type")
    if expected_type and not isinstance(value, expected_type):
        return False, f"Expected {expected_type.__name__}, got {type(value).__name__}"
    if "choices" in rules:
        if str(value).upper() not in rules["choices"]:
            return False, f"Must be one of: {', '.join(rules['choices'])}"
    if "min" in rules and expected_type in (int, float):
        if value < rules["min"]:
            return False, f"Must be >= {rules['min']}"
    if "max" in rules and expected_type in (int, float):
        if value > rules["max"]:
            return False, f"Must be <= {rules['max']}"
    return True, ""


def _parse_value(value_str: str, existing_value: Any) -> Any:
    """Parse value string to appropriate type based on existing value.

    Args:
        value_str: String value from command line
        existing_value: Existing value to determine type

    Returns:
        Parsed value with appropriate type
    """
    if existing_value is not None and isinstance(existing_value, list):
        return [item.strip() for item in value_str.split(",")]

    value_lower = value_str.lower()

    if value_lower in ("true", "yes", "1"):
        return True
    if value_lower in ("false", "no", "0"):
        return False

    try:
        return int(value_str)
    except ValueError:
        pass

    try:
        return float(value_str)
    except ValueError:
        pass

    return value_str


def _create_default_config() -> Dict[str, Any]:
    """Create default configuration dictionary.

    Returns:
        Default configuration dictionary
    """
    return {
        "exchange": {
            "name": "okx",
            "sandbox": True,
            "rate_limit": True,
            "enable_rate_limit": True,
        },
        "trading": {
            "symbols": ["BTC/USDT", "ETH/USDT"],
            "timeframe": "1h",
            "position_size": {
                "default_btc": 0.001,
                "max_position_pct": 0.1,
            },
        },
        "data": {
            "historical_path": "data/historical",
            "update_interval": 60,
            "lookback_periods": 1000,
        },
        "risk": {
            "max_daily_loss": 0.05,
            "max_drawdown": 0.15,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.05,
            "max_positions": 5,
        },
        "backtest": {
            "initial_capital": 10000,
            "commission": 0.001,
            "slippage": 0.0005,
        },
        "logging": {
            "level": "INFO",
            "log_to_file": True,
            "log_path": "logs",
            "rotation": "daily",
            "retention_days": 30,
        },
        "live": {
            "enabled": False,
            "dry_run": True,
        },
        "strategy": {
            "default": {
                "lookback": 20,
                "threshold": 0.02,
            },
        },
    }
