"""Database module for CryptoQuant platform.

Provides SQLAlchemy-based database operations for OHLCV data storage,
supporting both SQLite and PostgreSQL backends with connection pooling.
"""

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Generator, List, Optional

import structlog
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

logger = structlog.get_logger(__name__)

Base = declarative_base()


class OHLCVCandleDB(Base):
    """OHLCV candle database model."""
    
    __tablename__ = "ohlcv_candles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Integer, nullable=False, index=True)
    pair = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index("idx_pair_timeframe_timestamp", "pair", "timeframe", "timestamp", unique=True),
    )
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "open": self.open_price,
            "high": self.high_price,
            "low": self.low_price,
            "close": self.close_price,
            "volume": self.volume,
        }


class DataVersionDB(Base):
    """Track data updates and versioning."""
    
    __tablename__ = "data_versions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    pair = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    min_timestamp = Column(Integer, nullable=True)
    max_timestamp = Column(Integer, nullable=True)
    count = Column(Integer, nullable=False, default=0)
    last_update = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    data_source = Column(String(50), default="OKX")
    
    __table_args__ = (
        Index("idx_version_pair_tf", "pair", "timeframe", unique=True),
    )


class DataQualityDB(Base):
    """Store data quality check results."""
    
    __tablename__ = "data_quality"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    pair = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    check_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    total_records = Column(Integer, nullable=False)
    null_values = Column(Integer, default=0)
    invalid_prices = Column(Integer, default=0)
    negative_volumes = Column(Integer, default=0)
    gaps_detected = Column(Integer, default=0)
    is_valid = Column(Integer, default=1)
    notes = Column(String(500), nullable=True)


class DatabaseManager:
    """Database manager for OHLCV data operations."""
    
    def __init__(self, database_url: Optional[str] = None, **kwargs):
        """Initialize database manager.
        
        Args:
            database_url: Database URL (SQLite or PostgreSQL)
            **kwargs: Additional SQLAlchemy engine arguments
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL", "sqlite:///data/cryptoquant.db"
        )
        
        # Configure pool based on database type
        if self.database_url.startswith("sqlite"):
            # SQLite doesn't support pooling well
            self.engine = create_engine(
                self.database_url,
                poolclass=NullPool,
                connect_args={"check_same_thread": False},
            )
        else:
            pool_size = kwargs.get("pool_size", 5)
            max_overflow = kwargs.get("max_overflow", 10)
            pool_timeout = kwargs.get("pool_timeout", 30)
            
            self.engine = create_engine(
                self.database_url,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_pre_ping=True,
            )
        
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        
        logger.info(
            "database_initialized",
            database_url=self.database_url.replace("://", "://***@"),
            is_sqlite=self.database_url.startswith("sqlite"),
        )
    
    def create_tables(self) -> None:
        """Create all database tables."""
        Base.metadata.create_all(self.engine)
        logger.info("database_tables_created")
    
    def drop_tables(self) -> None:
        """Drop all database tables."""
        Base.metadata.drop_all(self.engine)
        logger.warning("database_tables_dropped")
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get database session context manager."""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def save_candles(
        self,
        candles: List[dict],
        pair: str,
        timeframe: str,
        batch_size: int = 1000,
    ) -> int:
        """Save candles to database with upsert support.
        
        Args:
            candles: List of candle dictionaries
            pair: Trading pair
            timeframe: Candle timeframe
            batch_size: Batch size for insertion
            
        Returns:
            Number of rows inserted/updated
        """
        if not candles:
            return 0
        
        count = 0
        
        with self.get_session() as session:
            for i in range(0, len(candles), batch_size):
                batch = candles[i:i + batch_size]
                
                for candle in batch:
                    candle_db = OHLCVCandleDB(
                        timestamp=candle["timestamp"],
                        pair=pair.upper(),
                        timeframe=timeframe,
                        open_price=float(candle["open"]),
                        high_price=float(candle["high"]),
                        low_price=float(candle["low"]),
                        close_price=float(candle["close"]),
                        volume=float(candle["volume"]),
                    )
                    session.merge(candle_db)
                    count += 1
                
                logger.debug(
                    "candles_batch_saved",
                    batch_size=len(batch),
                    pair=pair,
                    timeframe=timeframe,
                )
        
        logger.info(
            "candles_saved",
            count=count,
            pair=pair,
            timeframe=timeframe,
        )
        
        return count
    
    def get_candles(
        self,
        pair: str,
        timeframe: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Get candles from database.
        
        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            start_time: Start timestamp (optional)
            end_time: End timestamp (optional)
            limit: Maximum number of candles (optional)
            
        Returns:
            List of candle dictionaries
        """
        with self.get_session() as session:
            query = session.query(OHLCVCandleDB).filter(
                OHLCVCandleDB.pair == pair.upper(),
                OHLCVCandleDB.timeframe == timeframe,
            )
            
            if start_time:
                query = query.filter(OHLCVCandleDB.timestamp >= start_time)
            if end_time:
                query = query.filter(OHLCVCandleDB.timestamp <= end_time)
            
            query = query.order_by(OHLCVCandleDB.timestamp.asc())
            
            if limit:
                query = query.limit(limit)
            
            results = query.all()
            
            return [candle.to_dict() for candle in results]
    
    def get_latest_candle(self, pair: str, timeframe: str) -> Optional[dict]:
        """Get the latest candle for a pair and timeframe.
        
        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            
        Returns:
            Latest candle or None
        """
        with self.get_session() as session:
            result = session.query(OHLCVCandleDB).filter(
                OHLCVCandleDB.pair == pair.upper(),
                OHLCVCandleDB.timeframe == timeframe,
            ).order_by(
                OHLCVCandleDB.timestamp.desc()
            ).first()
            
            return result.to_dict() if result else None
    
    def get_candles_count(self, pair: str, timeframe: str) -> int:
        """Get the count of candles for a pair and timeframe.
        
        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            
        Returns:
            Number of candles
        """
        with self.get_session() as session:
            return session.query(OHLCVCandleDB).filter(
                OHLCVCandleDB.pair == pair.upper(),
                OHLCVCandleDB.timeframe == timeframe,
            ).count()
    
    def get_time_range(self, pair: str, timeframe: str) -> tuple[Optional[int], Optional[int]]:
        """Get the time range of stored candles.
        
        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            
        Returns:
            Tuple of (min_timestamp, max_timestamp)
        """
        with self.get_session() as session:
            result = session.query(
                func.min(OHLCVCandleDB.timestamp),
                func.max(OHLCVCandleDB.timestamp),
            ).filter(
                OHLCVCandleDB.pair == pair.upper(),
                OHLCVCandleDB.timeframe == timeframe,
            ).first()
            
            return result[0], result[1]
    
    def delete_candles(
        self,
        pair: str,
        timeframe: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> int:
        """Delete candles from database.
        
        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            start_time: Start timestamp (optional)
            end_time: End timestamp (optional)
            
        Returns:
            Number of deleted rows
        """
        with self.get_session() as session:
            query = session.query(OHLCVCandleDB).filter(
                OHLCVCandleDB.pair == pair.upper(),
                OHLCVCandleDB.timeframe == timeframe,
            )
            
            if start_time:
                query = query.filter(OHLCVCandleDB.timestamp >= start_time)
            if end_time:
                query = query.filter(OHLCVCandleDB.timestamp <= end_time)
            
            count = query.delete(synchronize_session=False)
            
            logger.info(
                "candles_deleted",
                count=count,
                pair=pair,
                timeframe=timeframe,
            )
            
            return count
    
    def update_data_version(
        self,
        pair: str,
        timeframe: str,
        count: int,
        data_source: str = "OKX",
    ) -> None:
        """Update data version info after data changes."""
        with self.get_session() as session:
            version = session.query(DataVersionDB).filter(
                DataVersionDB.pair == pair.upper(),
                DataVersionDB.timeframe == timeframe,
            ).first()
            
            time_range = self.get_time_range(pair, timeframe)
            
            if version:
                version.version += 1
                version.count = count
                version.min_timestamp = time_range[0]
                version.max_timestamp = time_range[1]
                version.last_update = datetime.now(timezone.utc)
                version.data_source = data_source
            else:
                version = DataVersionDB(
                    pair=pair.upper(),
                    timeframe=timeframe,
                    version=1,
                    min_timestamp=time_range[0],
                    max_timestamp=time_range[1],
                    count=count,
                    data_source=data_source,
                )
                session.add(version)
    
    def get_data_versions(self) -> list[dict]:
        """Get all data version information."""
        with self.get_session() as session:
            versions = session.query(DataVersionDB).all()
            return [
                {
                    "pair": v.pair,
                    "timeframe": v.timeframe,
                    "version": v.version,
                    "count": v.count,
                    "min_timestamp": v.min_timestamp,
                    "max_timestamp": v.max_timestamp,
                    "last_update": v.last_update,
                    "data_source": v.data_source,
                }
                for v in versions
            ]
    
    def validate_data_quality(self, pair: str, timeframe: str) -> dict:
        """Check data quality for a pair and timeframe."""
        with self.get_session() as session:
            candles = session.query(OHLCVCandleDB).filter(
                OHLCVCandleDB.pair == pair.upper(),
                OHLCVCandleDB.timeframe == timeframe,
            ).all()
            
            if not candles:
                return {"is_valid": False, "error": "No data found"}
            
            total = len(candles)
            null_values = sum(
                1 for c in candles
                if c.open_price is None or c.close_price is None
            )
            invalid_prices = sum(
                1 for c in candles
                if c.high_price < c.low_price or c.open_price <= 0
            )
            negative_volumes = sum(
                1 for c in candles if c.volume < 0
            )
            
            # Check for gaps
            timestamps = sorted([c.timestamp for c in candles])
            gaps = 0
            for i in range(1, len(timestamps)):
                gap = timestamps[i] - timestamps[i-1]
                # Expected gap based on timeframe
                expected = self._get_expected_interval(timeframe)
                if gap > expected * 2:
                    gaps += 1
            
            is_valid = (
                null_values == 0 and
                invalid_prices == 0 and
                negative_volumes == 0
            )
            
            quality = DataQualityDB(
                pair=pair.upper(),
                timeframe=timeframe,
                total_records=total,
                null_values=null_values,
                invalid_prices=invalid_prices,
                negative_volumes=negative_volumes,
                gaps_detected=gaps,
                is_valid=1 if is_valid else 0,
            )
            session.add(quality)
            
            return {
                "pair": pair,
                "timeframe": timeframe,
                "total": total,
                "null_values": null_values,
                "invalid_prices": invalid_prices,
                "negative_volumes": negative_volumes,
                "gaps": gaps,
                "is_valid": is_valid,
            }
    
    def _get_expected_interval(self, timeframe: str) -> int:
        """Get expected milliseconds interval for timeframe."""
        intervals = {
            "1m": 60 * 1000,
            "5m": 5 * 60 * 1000,
            "15m": 15 * 60 * 1000,
            "30m": 30 * 60 * 1000,
            "1h": 60 * 60 * 1000,
            "2h": 2 * 60 * 60 * 1000,
            "4h": 4 * 60 * 60 * 1000,
            "6h": 6 * 60 * 60 * 1000,
            "8h": 8 * 60 * 60 * 1000,
            "12h": 12 * 60 * 60 * 1000,
            "1d": 24 * 60 * 60 * 1000,
            "3d": 3 * 24 * 60 * 60 * 1000,
            "1w": 7 * 24 * 60 * 60 * 1000,
            "1M": 30 * 24 * 60 * 60 * 1000,
        }
        return intervals.get(timeframe, 60 * 60 * 1000)
    
    def close(self) -> None:
        self.engine.dispose()
        logger.info("database_connection_closed")


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def init_database(database_url: Optional[str] = None, **kwargs) -> DatabaseManager:
    """Initialize global database manager.
    
    Args:
        database_url: Database URL
        **kwargs: Additional engine arguments
        
    Returns:
        DatabaseManager instance
    """
    global _db_manager
    _db_manager = DatabaseManager(database_url, **kwargs)
    _db_manager.create_tables()
    return _db_manager


def get_db_manager() -> Optional[DatabaseManager]:
    """Get global database manager.
    
    Returns:
        DatabaseManager instance or None if not initialized
    """
    return _db_manager


def close_database() -> None:
    """Close global database connection."""
    global _db_manager
    if _db_manager:
        _db_manager.close()
        _db_manager = None
