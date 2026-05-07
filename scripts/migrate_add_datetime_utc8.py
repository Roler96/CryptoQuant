"""Database migration script to add datetime_utc8 field to candles table.

This script adds a datetime_utc8 TEXT column to the candles table and migrates
all existing rows by converting timestamp (ms) to UTC+8 datetime strings.

Usage:
    python scripts/migrate_add_datetime_utc8.py --dry-run  # Test mode
    python scripts/migrate_add_datetime_utc8.py            # Execute migration
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.datetime_utils import convert_to_utc8_str

DB_PATH = Path("data/cryptoquant.db")
BATCH_SIZE = 1000
PROGRESS_LOG_INTERVAL = 10


def check_column_exists(cursor: sqlite3.Cursor) -> bool:
    """Check if datetime_utc8 column already exists."""
    cursor.execute("PRAGMA table_info(candles)")
    columns = [col[1] for col in cursor.fetchall()]
    return "datetime_utc8" in columns


def add_datetime_utc8_column(conn: sqlite3.Connection, dry_run: bool = False) -> bool:
    """Add datetime_utc8 column to candles table.

    Args:
        conn: Database connection
        dry_run: If True, only check without executing ALTER TABLE

    Returns:
        True if column was added or already exists, False on error
    """
    cursor = conn.cursor()

    if check_column_exists(cursor):
        print("✓ datetime_utc8 column already exists")
        return True

    if dry_run:
        print("[DRY-RUN] Would add datetime_utc8 TEXT column to candles table")
        return True

    try:
        cursor.execute("ALTER TABLE candles ADD COLUMN datetime_utc8 TEXT")
        conn.commit()
        print("✓ Added datetime_utc8 TEXT column to candles table")
        return True
    except sqlite3.OperationalError as e:
        print(f"✗ Error adding column: {e}")
        return False


def migrate_batch(
    conn: sqlite3.Connection,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False
) -> int:
    """Migrate rows with NULL datetime_utc8 in batches.

    Args:
        conn: Database connection
        batch_size: Number of rows to process per batch
        dry_run: If True, only count rows without updating

    Returns:
        Number of rows processed
    """
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
    total_null = cursor.fetchone()[0]

    if total_null == 0:
        print("✓ No rows need migration (all datetime_utc8 values populated)")
        return 0

    print(f"Found {total_null} rows with NULL datetime_utc8")

    if dry_run:
        print(f"[DRY-RUN] Would migrate {total_null} rows in batches of {batch_size}")
        return total_null

    processed = 0
    batch_count = 0

    while True:
        cursor.execute(
            """
            SELECT id, timestamp
            FROM candles
            WHERE datetime_utc8 IS NULL
            LIMIT ?
            """,
            (batch_size,)
        )
        batch = cursor.fetchall()

        if not batch:
            break

        for row_id, timestamp in batch:
            datetime_str = convert_to_utc8_str(timestamp)
            cursor.execute(
                "UPDATE candles SET datetime_utc8 = ? WHERE id = ?",
                (datetime_str, row_id)
            )

        conn.commit()

        processed += len(batch)
        batch_count += 1

        if batch_count % PROGRESS_LOG_INTERVAL == 0:
            print(f"  Processed {processed}/{total_null} rows ({batch_count} batches)")

    print(f"✓ Migrated {processed} rows in {batch_count} batches")
    return processed


def verify_migration(conn: sqlite3.Connection) -> None:
    """Verify migration results."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
    null_count = cursor.fetchone()[0]

    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)
    print(f"NULL datetime_utc8 count: {null_count}")

    if null_count == 0:
        print("✓ All rows have datetime_utc8 values")
    else:
        print(f"✗ {null_count} rows still have NULL datetime_utc8")

    cursor.execute(
        """
        SELECT timestamp, datetime_utc8
        FROM candles
        WHERE datetime_utc8 IS NOT NULL
        LIMIT 5
        """
    )
    samples = cursor.fetchall()

    print("\nSample conversions:")
    for ts, dt in samples:
        print(f"  {ts} -> {dt}")

    print("=" * 60)


def main():
    """Run migration with optional dry-run mode."""
    parser = argparse.ArgumentParser(
        description="Add datetime_utc8 field to candles table"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test mode - check but don't execute changes"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("DATABASE MIGRATION: Add datetime_utc8 field")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"✗ Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))

    try:
        if not add_datetime_utc8_column(conn, dry_run=args.dry_run):
            sys.exit(1)

        if args.dry_run:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM candles")
            total_rows = cursor.fetchone()[0]
            print(f"[DRY-RUN] Total rows in candles table: {total_rows}")
            if check_column_exists(cursor):
                cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
                null_count = cursor.fetchone()[0]
                print(f"[DRY-RUN] Rows needing migration: {null_count}")
            else:
                print(f"[DRY-RUN] All {total_rows} rows would need migration (column doesn't exist yet)")
        else:
            processed = migrate_batch(conn, batch_size=BATCH_SIZE, dry_run=False)
            if processed > 0:
                verify_migration(conn)

        print("\n✓ Migration script completed")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()