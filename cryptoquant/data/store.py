"""SQLite OHLCV data storage."""
import re
import sqlite3
from pathlib import Path

import pandas as pd

from cryptoquant.exceptions import DataValidationError


_VALID_TABLE_NAME = re.compile(r"^ohlcv_[a-zA-Z0-9_]+_[a-zA-Z0-9_]+_\w+$")


def _table_name(exchange: str, symbol: str, timeframe: str) -> str:
    """Generate safe table name. BTC/USDT → BTC_USDT."""
    safe = symbol.replace("/", "_").replace("-", "_")
    name = f"ohlcv_{exchange}_{safe}_{timeframe}"
    if not _VALID_TABLE_NAME.match(name):
        raise DataValidationError(f"Invalid table name: {name}")
    return name


def _empty_df() -> pd.DataFrame:
    """Return empty OHLCV DataFrame with correct schema."""
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


class OHLCVStore:
    """SQLite-based OHLCV data store.

    Each (exchange, symbol, timeframe) gets its own table.
    Uses WAL mode for concurrent read access.
    """

    def __init__(self, db_path: str = "data/cryptoquant.db"):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-init connection with WAL mode."""
        if self._conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")
        return self._conn

    def _ensure_table(self, table: str) -> None:
        """Create table if not exists."""
        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                timestamp INTEGER PRIMARY KEY,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL
            )
        """)
        self.conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_ts
            ON {table}(timestamp)
        """)

    def _table_exists(self, table: str) -> bool:
        """Check if table exists."""
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def save(
        self,
        df: pd.DataFrame,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> int:
        """Save OHLCV data (UPSERT — existing timestamps are overwritten).

        Uses temp table + batch merge for performance.

        Returns:
            Number of rows written.
        """
        if df.empty:
            return 0

        table = _table_name(exchange, symbol, timeframe)
        self._ensure_table(table)

        rows = [
            (
                int(ts.timestamp() * 1000),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            )
            for ts, row in df.iterrows()
        ]

        tmp_table = f"_tmp_{table}"
        with self.conn:
            self.conn.execute(
                f"CREATE TEMP TABLE IF NOT EXISTS {tmp_table} "
                f"(timestamp INTEGER PRIMARY KEY, open REAL, high REAL, "
                f"low REAL, close REAL, volume REAL)"
            )
            self.conn.execute(f"DELETE FROM {tmp_table}")
            self.conn.executemany(
                f"INSERT INTO {tmp_table} VALUES (?, ?, ?, ?, ?, ?)", rows
            )
            self.conn.execute(
                f"INSERT OR REPLACE INTO {table} SELECT * FROM {tmp_table}"
            )
            self.conn.execute(f"DROP TABLE {tmp_table}")

        return len(rows)

    def load(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame:
        """Load OHLCV data from store.

        Args:
            start: Start timestamp (Unix ms, inclusive)
            end: End timestamp (Unix ms, inclusive)

        Returns:
            DataFrame with DatetimeIndex.
        """
        table = _table_name(exchange, symbol, timeframe)
        if not self._table_exists(table):
            return _empty_df()

        where = []
        params: list = []
        if start is not None:
            where.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            where.append("timestamp <= ?")
            params.append(end)

        sql = f"SELECT * FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY timestamp ASC"

        df = pd.read_sql_query(sql, self.conn, params=params)
        if df.empty:
            return _empty_df()

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_latest(
        self, exchange: str, symbol: str, timeframe: str
    ) -> int | None:
        """Get latest timestamp (ms) in store. None if empty."""
        table = _table_name(exchange, symbol, timeframe)
        if not self._table_exists(table):
            return None
        row = self.conn.execute(
            f"SELECT MAX(timestamp) FROM {table}"
        ).fetchone()
        return row[0] if row[0] is not None else None

    def get_range(
        self, exchange: str, symbol: str, timeframe: str
    ) -> tuple[int, int] | None:
        """Get (min, max) timestamp range. None if empty."""
        table = _table_name(exchange, symbol, timeframe)
        if not self._table_exists(table):
            return None
        row = self.conn.execute(
            f"SELECT MIN(timestamp), MAX(timestamp) FROM {table}"
        ).fetchone()
        if row[0] is None:
            return None
        return (row[0], row[1])

    def delete(
        self, exchange: str, symbol: str, timeframe: str
    ) -> int:
        """Delete all data for a symbol/timeframe. Returns rows deleted."""
        table = _table_name(exchange, symbol, timeframe)
        if not self._table_exists(table):
            return 0
        count = self.conn.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        self.conn.execute(f"DROP TABLE IF EXISTS {table}")
        return count

    def list_tables(self) -> list[str]:
        """List all OHLCV tables."""
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ohlcv_%'"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
