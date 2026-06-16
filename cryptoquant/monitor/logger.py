"""Unified logging configuration."""
import sys
from pathlib import Path

from loguru import logger


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    rotation: str = "10 MB",
    retention: str = "30 days",
    json_format: bool = False,
    alert_handler=None,
):
    """Configure loguru logging system."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.remove()

    # Console handler (colored)
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File handler
    if json_format:
        logger.add(
            log_path / "cryptoquant_{time:YYYY-MM-DD}.jsonl",
            level="DEBUG",
            format="{time} | {level} | {name}:{function}:{line} | {message}",
            rotation=rotation,
            retention=retention,
            serialize=True,
        )
    else:
        logger.add(
            log_path / "cryptoquant_{time:YYYY-MM-DD}.log",
            level="DEBUG",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                "{name}:{function}:{line} | {message}"
            ),
            rotation=rotation,
            retention=retention,
        )

    # Error log
    logger.add(
        log_path / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        rotation=rotation,
        retention=retention,
    )

    if alert_handler is not None:
        logger.add(
            alert_handler,
            level="ERROR",
            format="{message}",
        )

    logger.info(f"Logging configured: level={level}, dir={log_dir}")
    return logger
