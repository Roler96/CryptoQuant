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

# Keys per existence probe. SQLite's parameter limit is 999 on older builds,
# and each key costs one parameter per column.
_KEY_BATCH = 200

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
--
-- `funding_rate` is OKX's `fundingRate`, which is the *predicted* rate for
-- the period; `realized_rate` is `realizedRate`, what was actually charged.
-- They differ, and only the second one is a measurement.
CREATE TABLE IF NOT EXISTS funding (
    inst_id       TEXT    NOT NULL,
    funding_time  INTEGER NOT NULL,
    funding_rate  REAL    NOT NULL,
    realized_rate REAL,
    fetched_at    INTEGER NOT NULL,
    PRIMARY KEY (inst_id, funding_time)
);

-- Whether a backfill walk finished. OKX pages newest-to-oldest, so an
-- interrupted walk leaves a store whose oldest bar looks exactly like an
-- instrument that was listed late — the data cannot tell the two apart, and
-- resuming at the newest bar would strand the missing tail forever. A walk
-- clears its row on the way in and writes it back only on the way out.
CREATE TABLE IF NOT EXISTS ohlcv_sync (
    inst_id      TEXT    NOT NULL,
    timeframe    TEXT    NOT NULL,
    covered_from INTEGER NOT NULL,
    covered_to   INTEGER NOT NULL,
    complete     INTEGER NOT NULL DEFAULT 0,
    updated_at   INTEGER NOT NULL,
    PRIMARY KEY (inst_id, timeframe)
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


@dataclass(frozen=True)
class SyncState:
    """The span a completed backfill walk is known to have covered."""

    covered_from: int
    covered_to: int
    complete: bool


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
        """Insert OHLCV rows, refreshing ones already stored.

        Each row: (inst_id, timeframe, ts, open, high, low, close, volume,
        quote_volume).

        A re-fetched candle overwrites the stored one. OKX revises candles
        shortly after they close, and the exchange's value is the correct one:
        keeping the first copy seen would pin a bar to whatever the tape said
        in the second after it closed.
        """
        return self._upsert(
            table="ohlcv",
            columns=(
                "inst_id",
                "timeframe",
                "ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "quote_volume",
            ),
            key_columns=("inst_id", "timeframe", "ts"),
            rows=rows,
        )

    def upsert_funding(self, rows: Iterable[tuple]) -> WriteResult:
        """Each row: (inst_id, funding_time, funding_rate, realized_rate, fetched_at).

        Re-archiving corrects a stored row. A settlement swept immediately
        after it fires carries a predicted rate and often a null realized one;
        the next sweep brings the measured value, and it has to be allowed to
        land or the archive keeps the prediction forever.
        """
        return self._upsert(
            table="funding",
            columns=("inst_id", "funding_time", "funding_rate", "realized_rate", "fetched_at"),
            key_columns=("inst_id", "funding_time"),
            rows=rows,
        )

    def upsert_open_interest(self, rows: Iterable[tuple]) -> WriteResult:
        """Each row: (ccy, ts, oi_usd, volume_usd, fetched_at)."""
        return self._upsert(
            table="open_interest",
            columns=("ccy", "ts", "oi_usd", "volume_usd", "fetched_at"),
            key_columns=("ccy", "ts"),
            rows=rows,
        )

    def _upsert(
        self,
        table: str,
        columns: tuple[str, ...],
        key_columns: tuple[str, ...],
        rows: Iterable[tuple],
    ) -> WriteResult:
        """Insert or refresh `rows`, counting how many keys were new.

        Deliberately not `INSERT OR IGNORE`: that ignores *every* constraint,
        so a row with a null price or a missing timestamp is discarded as
        silently as a duplicate, and the archive ends up short of rows nobody
        was told about. `ON CONFLICT` narrows the tolerance to the one
        collision that is expected — the same key arriving twice.
        """
        rows = list(rows)
        if not rows:
            return WriteResult(0, 0)
        for row in rows:
            if len(row) != len(columns):
                raise ValueError(
                    f"{table}: row has {len(row)} values, expected {len(columns)} {columns}"
                )

        updated = tuple(c for c in columns if c not in key_columns)
        placeholders = ",".join("?" * len(columns))
        assignments = ",".join(f"{c}=excluded.{c}" for c in updated)
        statement = (
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "  # noqa: S608
            f"ON CONFLICT ({','.join(key_columns)}) DO UPDATE SET {assignments}"
        )

        with self.transaction() as conn:
            existing = _count_existing(conn, table, key_columns, columns, rows)
            conn.executemany(statement, rows)
        return WriteResult(seen=len(rows), new=len(rows) - existing)

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
        """Measured funding settlements, keyed by settlement time.

        Reads `realized_rate` — OKX's `realizedRate`, what the position was
        actually charged. `funding_rate` is `fundingRate`, the rate *predicted*
        for the period before it settled; the two differ, and charging a
        backtest the prediction is not a measurement of anything.

        Settlements whose realized rate was never archived are left out rather
        than filled in from the prediction, so `ActualFunding` raises on them
        the same way it raises on a settlement that is missing outright.
        """
        rows = self._conn.execute(
            "SELECT funding_time, realized_rate FROM funding "
            "WHERE inst_id=? AND realized_rate IS NOT NULL ORDER BY funding_time",
            (inst_id,),
        ).fetchall()
        return {int(row["funding_time"]): float(row["realized_rate"]) for row in rows}

    # ---- backfill resumption -------------------------------------------

    def begin_ohlcv_sync(self, inst_id: str, timeframe: str, at_ms: int) -> None:
        """Mark a walk as in progress, so an interrupted one stays visible."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO ohlcv_sync (inst_id, timeframe, covered_from, covered_to, "
                "complete, updated_at) VALUES (?,?,0,0,0,?) "
                "ON CONFLICT (inst_id, timeframe) DO UPDATE SET complete=0, "
                "updated_at=excluded.updated_at",
                (inst_id, timeframe, at_ms),
            )

    def finish_ohlcv_sync(
        self, inst_id: str, timeframe: str, covered_from: int, covered_to: int, at_ms: int
    ) -> None:
        """Record that a walk covered [covered_from, covered_to] without a hole."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO ohlcv_sync (inst_id, timeframe, covered_from, covered_to, "
                "complete, updated_at) VALUES (?,?,?,?,1,?) "
                "ON CONFLICT (inst_id, timeframe) DO UPDATE SET "
                "covered_from=excluded.covered_from, covered_to=excluded.covered_to, "
                "complete=1, updated_at=excluded.updated_at",
                (inst_id, timeframe, covered_from, covered_to, at_ms),
            )

    def ohlcv_sync_state(self, inst_id: str, timeframe: str) -> SyncState | None:
        row = self._conn.execute(
            "SELECT covered_from, covered_to, complete FROM ohlcv_sync "
            "WHERE inst_id=? AND timeframe=?",
            (inst_id, timeframe),
        ).fetchone()
        if row is None:
            return None
        return SyncState(
            covered_from=int(row["covered_from"]),
            covered_to=int(row["covered_to"]),
            complete=bool(row["complete"]),
        )

    def recent_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM archive_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
        )


def _count_existing(
    conn: sqlite3.Connection,
    table: str,
    key_columns: tuple[str, ...],
    columns: tuple[str, ...],
    rows: list[tuple],
) -> int:
    """How many of `rows`' keys the table already holds.

    Counted before writing, because an upsert that both inserts and updates
    cannot be told apart afterwards by `total_changes`.
    """
    positions = [columns.index(name) for name in key_columns]
    keys = {tuple(row[position] for position in positions) for row in rows}
    key_list = sorted(keys)

    found = 0
    width = len(key_columns)
    for start in range(0, len(key_list), _KEY_BATCH):
        chunk = key_list[start : start + _KEY_BATCH]
        values = ",".join(f"({','.join('?' * width)})" for _ in chunk)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} "  # noqa: S608 - identifiers are module constants
            f"WHERE ({','.join(key_columns)}) IN (VALUES {values})",
            [value for key in chunk for value in key],
        ).fetchone()
        found += int(row["n"])
    return found
