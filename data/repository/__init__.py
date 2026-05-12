"""Data repository module for CryptoQuant platform.

Provides a unified data access layer backed by SQLite.
"""

from data.repository.base import DataRepository
from data.repository.sqlite import SQLiteRepository

# Singleton instance
_repository: DataRepository | None = None


def get_repository(db_path: str | None = None) -> DataRepository:
    """Get or create the global data repository instance.

    Uses singleton pattern: first call initializes, subsequent calls
    return the same instance.

    Args:
        db_path: Optional SQLite database path. Only used on first call.

    Returns:
        DataRepository instance (SQLite-backed)
    """
    global _repository
    if _repository is None:
        _repository = SQLiteRepository(db_path=db_path)
    return _repository


def reset_repository() -> None:
    """Reset the global repository instance. Useful for testing."""
    global _repository
    if _repository is not None:
        try:
            _repository.close()
        except AttributeError:
            pass
        _repository = None


__all__ = [
    "DataRepository",
    "SQLiteRepository",
    "get_repository",
    "reset_repository",
]
