"""Migrate all Parquet data to database."""

import sys
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import init_database
from data.loader import save_candles, use_database
from data.models import OHLCVCandle
from data.storage import load_historical_data

logger = structlog.get_logger(__name__)


def migrate_pair_timeframe(pair: str, timeframe: str) -> int:
    try:
        df = load_historical_data(pair, timeframe)
        
        candles = [
            OHLCVCandle(
                timestamp=row["timestamp"],
                open_price=row["open"],
                high_price=row["high"],
                low_price=row["low"],
                close_price=row["close"],
                volume=row["volume"],
                pair=pair,
                timeframe=timeframe,
            )
            for _, row in df.iterrows()
        ]
        
        count = save_candles(candles, pair, timeframe)
        logger.info("Migrated", pair=pair, timeframe=timeframe, count=count)
        return count
        
    except FileNotFoundError:
        return 0
    except Exception as e:
        logger.error("Failed", pair=pair, timeframe=timeframe, error=str(e))
        return 0


def main():
    print("=" * 70)
    print("Migrating All Data: Parquet → Database")
    print("=" * 70)
    
    if not use_database():
        print("\n⚠ Database storage not enabled!")
        print("Set storage_mode: database in config/config.yaml")
        return 1
    
    init_database()
    
    data_dir = Path("data/historical")
    parquet_files = list(data_dir.glob("*.parquet"))
    
    print(f"\nFound {len(parquet_files)} Parquet files")
    
    pairs_timeframes = set()
    for f in parquet_files:
        parts = f.stem.split("_")
        if len(parts) >= 3:
            pair = f"{parts[0].upper()}/{parts[1].upper()}"
            timeframe = "_".join(parts[2:])
            pairs_timeframes.add((pair, timeframe))
    
    print(f"Unique pairs/timeframes: {len(pairs_timeframes)}")
    print()
    
    total = 0
    failed = 0
    
    for i, (pair, timeframe) in enumerate(sorted(pairs_timeframes), 1):
        print(f"[{i}/{len(pairs_timeframes)}] {pair} {timeframe}...", end=" ")
        count = migrate_pair_timeframe(pair, timeframe)
        if count > 0:
            print(f"✓ {count:,}")
            total += count
        else:
            print("✗ Failed")
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"✓ Migration Complete!")
    print("=" * 70)
    print(f"\nTotal: {total:,} candles")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
