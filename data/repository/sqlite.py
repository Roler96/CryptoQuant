"""SQLite repository implementation for CryptoQuant platform.

Stores OHLCV data in a single 'candles' table with:
- Composite primary key (pair, timeframe, timestamp) for natural dedup
- NUMERIC columns for price/volume to preserve Decimal precision
- WAL mode for read-write concurrency
- ISO 8601 UTC time string for human readability
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import structlog
from sqlalchemy import (
    Column,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from data.models import OHLCVCandle
from data.repository.base import DataRepository

logger = structlog.get_logger(__name__)

Base = declarative_base()

# Default SQLite database path
DEFAULT_DB_PATH = "data/cryptoquant.db"


class CandleModel(Base):
    """SQLAlchemy ORM model for the candles table."""

    __tablename__ = "candles"

    pair = Column(String(20), primary_key=True, nullable=False)
    timeframe = Column(String(10), primary_key=True, nullable=False)
    timestamp = Column(Integer, primary_key=True, nullable=False)
    iso_time = Column(String(30), nullable=False)
    open = Column(Numeric(20, 8), nullable=False)
    high = Column(Numeric(20, 8), nullable=False)
    low = Column(Numeric(20, 8), nullable=False)
    close = Column(Numeric(20, 8), nullable=False)
    volume = Column(Numeric(20, 8), nullable=False)

    __table_args__ = (
        Index("idx_candles_pair_tf", "pair", "timeframe"),
    )

    def to_candle(self) -> OHLCVCandle:
        """Convert ORM row to OHLCVCandle dataclass."""
        return OHLCVCandle(
            pair=self.pair,
            timeframe=self.timeframe,
            timestamp=self.timestamp,
            open=Decimal(str(self.open)),
            high=Decimal(str(self.high)),
            low=Decimal(str(self.low)),
            close=Decimal(str(self.close)),
            volume=Decimal(str(self.volume)),
        )

    @classmethod
    def from_candle(cls, candle: OHLCVCandle) -> "CandleModel":
        """Create ORM row from OHLCVCandle dataclass."""
        return cls(
            pair=candle.pair,
            timeframe=candle.timeframe,
            timestamp=candle.timestamp,
            iso_time=candle.iso_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        )


class SQLiteRepository(DataRepository):
    """SQLite-backed data repository for OHLCV candles.

    Features:
    - Composite primary key (pair, timeframe, timestamp) for dedup
    - NUMERIC(20, 8) columns for exact Decimal precision
    - WAL journal mode for concurrent read/write
    - Bulk upsert via INSERT OR REPLACE
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize SQLite repository.

        Args:
            db_path: Path to SQLite database file (default: data/cryptoquant.db)
        """
        self.db_path = db_path or DEFAULT_DB_PATH

        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            pool_pre_ping=True,
        )

        # Optimize SQLite settings
        with self.engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA cache_size=-64000"))  # 64MB cache
            conn.execute(text("PRAGMA busy_timeout=5000"))  # 5s wait on lock
            conn.commit()

        Base.metadata.create_all(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        logger.info(
            "sqlite_repository_initialized",
            db_path=self.db_path,
        )

    def save_candles(
        self,
        candles: List[OHLCVCandle],
        pair: str,
        timeframe: str,
    ) -> int:
        """Batch save candles with upsert semantics.

        Uses SQLite INSERT OR REPLACE (ON CONFLICT DO UPDATE) on the composite
        primary key (pair, timeframe, timestamp) to handle duplicates cleanly.

        Args:
            candles: List of OHLCV candle objects
            pair: Trading pair
            timeframe: Candle timeframe

        Returns:
            Number of rows inserted or updated
        """
        if not candles:
            return 0

        with self.Session() as session:
            for candle in candles:
                values = {
                    "pair": candle.pair,
                    "timeframe": candle.timeframe,
                    "timestamp": candle.timestamp,
                    "iso_time": candle.iso_time,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
                stmt = sqlite_upsert(CandleModel).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["pair", "timeframe", "timestamp"],
                    set_={
                        "iso_time": candle.iso_time,
                        "open": candle.open,
                        "high": candle.high,
                        "low": candle.low,
                        "close": candle.close,
                        "volume": candle.volume,
                    },
                )
                session.execute(stmt)
            session.commit()

        logger.info(
            "candles_saved",
            pair=pair,
            timeframe=timeframe,
            count=len(candles),
        )
        return len(candles)

    def load_candles(
        self,
        pair: str,
        timeframe: str,
        since: Optional[int] = None,
        until: Optional[int] = None,
        limit: Optional[int] = None,
        order: Optional[str] = "asc",
    ) -> List[OHLCVCandle]:
        """Load candles as OHLCVCandle objects.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            since: Start timestamp (ms, inclusive)
            until: End timestamp (ms, inclusive)
            limit: Maximum number of candles
            order: Sort order ("asc" for oldest-first, "desc" for newest-first)

        Returns:
            List of OHLCVCandle sorted by timestamp in specified order
        """
        with self.Session() as session:
            stmt = select(CandleModel).where(
                CandleModel.pair == pair,
                CandleModel.timeframe == timeframe,
            )

            if since is not None:
                stmt = stmt.where(CandleModel.timestamp >= since)
            if until is not None:
                stmt = stmt.where(CandleModel.timestamp <= until)

            if order == "desc":
                stmt = stmt.order_by(CandleModel.timestamp.desc())
            else:
                stmt = stmt.order_by(CandleModel.timestamp.asc())

            if limit is not None:
                stmt = stmt.limit(limit)

            rows = session.execute(stmt).scalars().all()

        return [row.to_candle() for row in rows]

    def load_as_dataframe(
        self,
        pair: str,
        timeframe: str,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> pd.DataFrame:
        """Load candles as pandas DataFrame for backtest engine.

        Columns: timestamp, open, high, low, close, volume
        (Matches the expected format for Backtrader PandasDataFeed)

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            since: Start timestamp (ms, inclusive)
            until: End timestamp (ms, inclusive)

        Returns:
            DataFrame sorted by timestamp ascending
        """
        candles = self.load_candles(pair, timeframe, since=since, until=until)

        if not candles:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        # Convert Decimal to float for DataFrame (Backtrader expects float)
        data = {
            "timestamp": [c.timestamp for c in candles],
            "open": [float(c.open) for c in candles],
            "high": [float(c.high) for c in candles],
            "low": [float(c.low) for c in candles],
            "close": [float(c.close) for c in candles],
            "volume": [float(c.volume) for c in candles],
        }

        return pd.DataFrame(data)

    def get_latest_timestamp(self, pair: str, timeframe: str) -> Optional[int]:
        """Get the most recent timestamp for a pair/timeframe."""
        with self.Session() as session:
            result = session.execute(
                select(func.max(CandleModel.timestamp)).where(
                    CandleModel.pair == pair,
                    CandleModel.timeframe == timeframe,
                )
            ).scalar()
            return result

    def get_earliest_timestamp(self, pair: str, timeframe: str) -> Optional[int]:
        """Get the oldest timestamp for a pair/timeframe."""
        with self.Session() as session:
            result = session.execute(
                select(func.min(CandleModel.timestamp)).where(
                    CandleModel.pair == pair,
                    CandleModel.timeframe == timeframe,
                )
            ).scalar()
            return result

    def count(self, pair: str, timeframe: str) -> int:
        """Count candles for a pair/timeframe."""
        with self.Session() as session:
            result = session.execute(
                select(func.count()).where(
                    CandleModel.pair == pair,
                    CandleModel.timeframe == timeframe,
                )
            ).scalar()
            return result or 0

    def exists(self, pair: str, timeframe: str) -> bool:
        """Check if any data exists for a pair/timeframe."""
        return self.count(pair, timeframe) > 0

    def delete(
        self,
        pair: str,
        timeframe: str,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> int:
        """Delete candles for a pair/timeframe."""
        with self.Session() as session:
            stmt = CandleModel.__table__.delete().where(
                CandleModel.pair == pair,
                CandleModel.timeframe == timeframe,
            )

            if since is not None:
                stmt = stmt.where(CandleModel.timestamp >= since)
            if until is not None:
                stmt = stmt.where(CandleModel.timestamp <= until)

            result = session.execute(stmt)
            session.commit()
            deleted = result.rowcount or 0

        logger.info(
            "candles_deleted",
            pair=pair,
            timeframe=timeframe,
            count=deleted,
        )
        return deleted

    def list_pairs_timeframes(self) -> List[Tuple[str, str]]:
        """List all stored (pair, timeframe) combinations."""
        with self.Session() as session:
            result = session.execute(
                select(CandleModel.pair, CandleModel.timeframe).distinct()
            ).all()
            return [(r[0], r[1]) for r in result]

    def close(self) -> None:
        """Dispose the engine and release connections."""
        self.engine.dispose()
        logger.info("sqlite_repository_closed")

    def __enter__(self) -> "SQLiteRepository":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
