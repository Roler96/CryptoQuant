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
        """Convert to dictionary."""
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
    
    def close(self) -> None:
        """Close database connection."""
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
