"""SQLite storage for market and derivative data.

All timestamps are epoch milliseconds, UTC, and always refer to the *open*
time of a bar or the settlement time of a funding period.  Nothing in this
module ever fills gaps: missing data stays missing so that the quality layer
and the engine can react to it explicitly.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("data/cq.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    inst_id       TEXT    NOT NULL,
    timeframe     TEXT    NOT NULL,
    ts            INTEGER NOT NULL,
    open          REAL    NOT NULL,
    high          REAL    NOT NULL,
    low           REAL    NOT NULL,
    close         REAL    NOT NULL,
    volume        REAL    NOT NULL,
    quote_volume  REAL,
    PRIMARY KEY (inst_id, timeframe, ts)
);

-- Funding settlements. OKX only serves ~3 months of history, so rows here
-- are irreplaceable once they age out of the API.
CREATE TABLE IF NOT EXISTS funding (
    inst_id       TEXT    NOT NULL,
    funding_time  INTEGER NOT NULL,
    funding_rate  REAL    NOT NULL,
    realized_rate REAL,
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (inst_id, funding_time)
);

-- Open interest / volume, from /rubik/stat/contracts/open-interest-volume.
-- Keyed by currency (the endpoint is not per-instrument). Values are USD.
-- Only ~30 days of history is served: this ages out 4x faster than funding.
CREATE TABLE IF NOT EXISTS open_interest (
    ccy         TEXT    NOT NULL,
    ts          INTEGER NOT NULL,
    oi_usd      REAL,
    volume_usd  REAL,
    fetched_at  INTEGER NOT NULL,
    PRIMARY KEY (ccy, ts)
);

-- Audit trail: every archive run, successful or not. Makes "did the cron
-- actually run last night?" answerable without reading logs.
CREATE TABLE IF NOT EXISTS archive_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL,
    target       TEXT    NOT NULL,
    started_at   INTEGER NOT NULL,
    finished_at  INTEGER,
    rows_seen    INTEGER NOT NULL DEFAULT 0,
    rows_new     INTEGER NOT NULL DEFAULT 0,
    ok           INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_archive_runs_kind_time
    ON archive_runs (kind, started_at);
"""


@dataclass(frozen=True)
class WriteResult:
    """How many rows an upsert saw versus actually added."""

    seen: int
    new: int


class Store:
    """Thin SQLite wrapper. Not thread-safe; open one per process."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH):
        self.path = Path(path)
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    # ---- writes -------------------------------------------------------

    def upsert_ohlcv(self, rows: Iterable[tuple]) -> WriteResult:
        """Insert OHLCV rows, ignoring ones already stored.

        Each row: (inst_id, timeframe, ts, open, high, low, close, volume,
        quote_volume).
        """
        rows = list(rows)
        if not rows:
            return WriteResult(0, 0)
        with self.transaction() as conn:
            before = _total_changes(conn)
            conn.executemany(
                "INSERT OR IGNORE INTO ohlcv "
                "(inst_id, timeframe, ts, open, high, low, close, volume, quote_volume) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            new = _total_changes(conn) - before
        return WriteResult(seen=len(rows), new=new)

    def upsert_funding(self, rows: Iterable[tuple]) -> WriteResult:
        """Each row: (inst_id, funding_time, funding_rate, realized_rate, fetched_at)."""
        rows = list(rows)
        if not rows:
            return WriteResult(0, 0)
        with self.transaction() as conn:
            before = _total_changes(conn)
            conn.executemany(
                "INSERT OR IGNORE INTO funding "
                "(inst_id, funding_time, funding_rate, realized_rate, fetched_at) "
                "VALUES (?,?,?,?,?)",
                rows,
            )
            new = _total_changes(conn) - before
        return WriteResult(seen=len(rows), new=new)

    def upsert_open_interest(self, rows: Iterable[tuple]) -> WriteResult:
        """Each row: (ccy, ts, oi_usd, volume_usd, fetched_at)."""
        rows = list(rows)
        if not rows:
            return WriteResult(0, 0)
        with self.transaction() as conn:
            before = _total_changes(conn)
            conn.executemany(
                "INSERT OR IGNORE INTO open_interest "
                "(ccy, ts, oi_usd, volume_usd, fetched_at) VALUES (?,?,?,?,?)",
                rows,
            )
            new = _total_changes(conn) - before
        return WriteResult(seen=len(rows), new=new)

    # ---- archive run audit --------------------------------------------

    def start_run(self, kind: str, target: str, started_at: int) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO archive_runs (kind, target, started_at) VALUES (?,?,?)",
                (kind, target, started_at),
            )
        return int(cur.lastrowid or 0)

    def finish_run(
        self,
        run_id: int,
        finished_at: int,
        result: WriteResult,
        ok: bool,
        error: str | None = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE archive_runs SET finished_at=?, rows_seen=?, rows_new=?, ok=?, "
                "error=? WHERE id=?",
                (finished_at, result.seen, result.new, int(ok), error, run_id),
            )

    # ---- reads --------------------------------------------------------

    def coverage(self, table: str, key_column: str, key: str, ts_column: str) -> tuple:
        """Return (count, min_ts, max_ts) for one series."""
        row = self._conn.execute(
            f"SELECT COUNT(*) AS n, MIN({ts_column}) AS lo, MAX({ts_column}) AS hi "  # noqa: S608
            f"FROM {table} WHERE {key_column}=?",
            (key,),
        ).fetchone()
        return (row["n"], row["lo"], row["hi"])

    def funding_coverage(self, inst_id: str) -> tuple:
        return self.coverage("funding", "inst_id", inst_id, "funding_time")

    def ohlcv_coverage(self, inst_id: str, timeframe: str) -> tuple:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n, MIN(ts) AS lo, MAX(ts) AS hi FROM ohlcv "
            "WHERE inst_id=? AND timeframe=?",
            (inst_id, timeframe),
        ).fetchone()
        return (row["n"], row["lo"], row["hi"])

    def load_ohlcv(
        self,
        inst_id: str,
        timeframe: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        """Stored bars as a DataFrame indexed by UTC open time, ascending.

        `end_ms` is exclusive so that adjacent ranges do not overlap.
        """
        query = "SELECT ts, open, high, low, close, volume, quote_volume FROM ohlcv "
        query += "WHERE inst_id=? AND timeframe=?"
        params: list = [inst_id, timeframe]
        if start_ms is not None:
            query += " AND ts >= ?"
            params.append(start_ms)
        if end_ms is not None:
            query += " AND ts < ?"
            params.append(end_ms)
        query += " ORDER BY ts ASC"

        frame = pd.read_sql_query(query, self._conn, params=params)
        frame.index = pd.to_datetime(frame.pop("ts"), unit="ms", utc=True)
        frame.index.name = "ts"
        return frame

    def open_interest_coverage(self, ccy: str) -> tuple:
        return self.coverage("open_interest", "ccy", ccy, "ts")

    def load_funding(self, inst_id: str) -> dict[int, float]:
        """Archived funding settlements, keyed by settlement time."""
        rows = self._conn.execute(
            "SELECT funding_time, funding_rate FROM funding WHERE inst_id=? "
            "ORDER BY funding_time",
            (inst_id,),
        ).fetchall()
        return {int(row["funding_time"]): float(row["funding_rate"]) for row in rows}

    def recent_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM archive_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
        )


def _total_changes(conn: sqlite3.Connection) -> int:
    return conn.total_changes
