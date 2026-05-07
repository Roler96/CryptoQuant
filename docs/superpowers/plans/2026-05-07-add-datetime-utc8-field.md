# Add datetime_utc8 Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add human-readable UTC+8 datetime string field to candles database table and update all data insertion scripts to populate it.

**Architecture:** Create shared datetime conversion utility, batch migration script for existing data, modify fetch scripts to populate new field during INSERT.

**Tech Stack:** Python 3.10+, SQLite, datetime.timezone

---

## File Structure

| File | Purpose | Status |
|------|---------|--------|
| `scripts/utils/datetime_utils.py` | Shared UTC+8 conversion function | Create |
| `scripts/migrate_add_datetime_utc8.py` | Migration script for existing data | Create |
| `scripts/fetch_data_simple.py` | Data insertion script | Modify |
| `scripts/fetch_continuous.py` | Data insertion script | Modify |
| `scripts/fetch_all_data.py` | Data insertion script | Modify |
| `tests/test_datetime_conversion.py` | Unit tests | Create |

---

## Task 1: Create datetime_utils module with conversion function

**Files:**
- Create: `scripts/utils/__init__.py`
- Create: `scripts/utils/datetime_utils.py`
- Test: `tests/test_datetime_conversion.py`

- [ ] **Step 1: Create utils package directory**

```bash
mkdir -p scripts/utils
touch scripts/utils/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_datetime_conversion.py`:

```python
"""Unit tests for datetime conversion utility."""

import pytest
from datetime import datetime, timezone, timedelta


# Import the function we'll create
# from scripts.utils.datetime_utils import convert_to_utc8_str


def test_convert_known_timestamp():
    """Test conversion of known timestamp."""
    # Manual calculation: 1746538080000 ms = 1746538080 seconds
    # 2026-05-06 13:28:00 UTC -> 2026-05-06 21:28:00 UTC+8
    ts = 1746538080000
    result = convert_to_utc8_str(ts)
    assert result == "2026-05-06 21:28:00"


def test_convert_epoch():
    """Test Unix epoch conversion."""
    # 1970-01-01 00:00:00 UTC -> 1970-01-01 08:00:00 UTC+8
    ts = 0
    result = convert_to_utc8_str(ts)
    assert result == "1970-01-01 08:00:00"


def test_format_consistency():
    """Test output format is consistent."""
    ts = int(datetime.now().timestamp() * 1000)
    result = convert_to_utc8_str(ts)
    
    # Format: YYYY-MM-DD HH:MM:SS (19 chars)
    assert len(result) == 19
    assert result[4] == '-'  # First separator
    assert result[7] == '-'  # Second separator
    assert result[10] == ' '  # Date-time separator
    assert result[13] == ':'  # First time separator
    assert result[16] == ':'  # Second time separator


def test_negative_timestamp():
    """Test negative timestamp (before Unix epoch)."""
    # 1969-12-31 23:59:59 UTC -> 1970-01-01 07:59:59 UTC+8
    ts = -1000
    result = convert_to_utc8_str(ts)
    assert result == "1970-01-01 07:59:59"


def test_large_timestamp():
    """Test large timestamp (year 2100+)."""
    # Approximate: 2100-01-01 00:00:00 UTC
    ts = 4102444800000
    result = convert_to_utc8_str(ts)
    assert result.startswith("2100-")
    assert result.endswith(":00")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_datetime_conversion.py -v`
Expected: FAIL with "NameError: name 'convert_to_utc8_str' is not defined"

- [ ] **Step 4: Write implementation**

Create `scripts/utils/datetime_utils.py`:

```python
"""Datetime conversion utilities for CryptoQuant platform.

Provides timezone-aware datetime conversion functions for displaying
timestamps in human-readable formats.
"""

from datetime import datetime, timezone, timedelta


# UTC+8 timezone constant
UTC8 = timezone(timedelta(hours=8))


def convert_to_utc8_str(timestamp_ms: int) -> str:
    """Convert millisecond timestamp to UTC+8 datetime string.
    
    Args:
        timestamp_ms: Unix timestamp in milliseconds
        
    Returns:
        UTC+8 datetime string in format 'YYYY-MM-DD HH:MM:SS'
        
    Examples:
        >>> convert_to_utc8_str(1746538080000)
        '2026-05-06 21:28:00'
        
        >>> convert_to_utc8_str(0)
        '1970-01-01 08:00:00'
    """
    # Convert milliseconds to seconds
    timestamp_seconds = timestamp_ms / 1000
    
    # Create datetime with UTC+8 timezone
    dt = datetime.fromtimestamp(timestamp_seconds, tz=UTC8)
    
    # Format to string
    return dt.strftime('%Y-%m-%d %H:%M:%S')
```

Update `tests/test_datetime_conversion.py` to import:

```python
"""Unit tests for datetime conversion utility."""

import pytest
from datetime import datetime, timezone, timedelta


# Import the function we created
from scripts.utils.datetime_utils import convert_to_utc8_str


def test_convert_known_timestamp():
    """Test conversion of known timestamp."""
    ts = 1746538080000
    result = convert_to_utc8_str(ts)
    assert result == "2026-05-06 21:28:00"


def test_convert_epoch():
    """Test Unix epoch conversion."""
    ts = 0
    result = convert_to_utc8_str(ts)
    assert result == "1970-01-01 08:00:00"


def test_format_consistency():
    """Test output format is consistent."""
    ts = int(datetime.now().timestamp() * 1000)
    result = convert_to_utc8_str(ts)
    
    assert len(result) == 19
    assert result[4] == '-'
    assert result[7] == '-'
    assert result[10] == ' '
    assert result[13] == ':'
    assert result[16] == ':'


def test_negative_timestamp():
    """Test negative timestamp (before Unix epoch)."""
    ts = -1000
    result = convert_to_utc8_str(ts)
    assert result == "1970-01-01 07:59:59"


def test_large_timestamp():
    """Test large timestamp (year 2100+)."""
    ts = 4102444800000
    result = convert_to_utc8_str(ts)
    assert result.startswith("2100-")
    assert result.endswith(":00")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_datetime_conversion.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit utility module**

```bash
git add scripts/utils/__init__.py scripts/utils/datetime_utils.py tests/test_datetime_conversion.py
git commit -m "feat: add datetime conversion utility with UTC+8 support"
```

---

## Task 2: Create database migration script

**Files:**
- Create: `scripts/migrate_add_datetime_utc8.py`

- [ ] **Step 1: Write migration script**

Create `scripts/migrate_add_datetime_utc8.py`:

```python
#!/usr/bin/env python3
"""Database migration script: Add datetime_utc8 field to candles table.

This script:
1. Adds the datetime_utc8 TEXT column to the candles table
2. Migrates all existing rows (218,900+) by calculating UTC+8 datetime strings
3. Uses batch processing to avoid memory issues
"""

import sys
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.datetime_utils import convert_to_utc8_str


# Database path
DB_PATH = Path("data/cryptoquant.db")
BATCH_SIZE = 1000


def add_datetime_utc8_column(conn: sqlite3.Connection) -> None:
    """Add datetime_utc8 column if it doesn't exist.
    
    Args:
        conn: SQLite database connection
    """
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(candles)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'datetime_utc8' not in columns:
        print("Adding datetime_utc8 column...")
        cursor.execute("ALTER TABLE candles ADD COLUMN datetime_utc8 TEXT")
        conn.commit()
        print("✓ Column added successfully")
    else:
        print("✓ datetime_utc8 column already exists")


def migrate_batch(conn: sqlite3.Connection, batch_num: int) -> int:
    """Migrate a batch of rows with NULL datetime_utc8.
    
    Args:
        conn: SQLite database connection
        batch_num: Current batch number for logging
        
    Returns:
        Number of rows migrated in this batch
    """
    cursor = conn.cursor()
    
    # Fetch rows with NULL datetime_utc8
    cursor.execute("""
        SELECT id, timestamp FROM candles
        WHERE datetime_utc8 IS NULL
        LIMIT ?
    """, (BATCH_SIZE,))
    
    rows = cursor.fetchall()
    
    if not rows:
        return 0
    
    # Update each row
    for row_id, timestamp in rows:
        utc8_str = convert_to_utc8_str(timestamp)
        cursor.execute("""
            UPDATE candles
            SET datetime_utc8 = ?
            WHERE id = ?
        """, (utc8_str, row_id))
    
    conn.commit()
    
    return len(rows)


def run_migration() -> None:
    """Execute the full migration process."""
    print("="*60)
    print("Database Migration: Add datetime_utc8 field")
    print("="*60)
    print(f"Database: {DB_PATH}")
    print(f"Batch size: {BATCH_SIZE}")
    print()
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    
    # Step 1: Add column
    add_datetime_utc8_column(conn)
    print()
    
    # Check current state
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
    null_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM candles")
    total_count = cursor.fetchone()[0]
    
    print(f"Total rows: {total_count}")
    print(f"Rows needing migration: {null_count}")
    print()
    
    if null_count == 0:
        print("✓ All rows already migrated, nothing to do")
        conn.close()
        return
    
    # Step 2: Migrate in batches
    print("Starting batch migration...")
    batch_num = 0
    migrated_total = 0
    
    while True:
        batch_num += 1
        migrated = migrate_batch(conn, batch_num)
        
        if migrated == 0:
            break
        
        migrated_total += migrated
        
        # Progress logging every 10 batches
        if batch_num % 10 == 0:
            cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
            remaining = cursor.fetchone()[0]
            print(f"Batch {batch_num}: Migrated {migrated} rows "
                  f"(Total: {migrated_total}, Remaining: {remaining})")
    
    print()
    print("="*60)
    print("Migration Complete")
    print("="*60)
    print(f"Total batches: {batch_num}")
    print(f"Total rows migrated: {migrated_total}")
    
    # Final verification
    cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
    final_null = cursor.fetchone()[0]
    
    if final_null == 0:
        print("✓ Verification: All rows have datetime_utc8 values")
    else:
        print(f"⚠ WARNING: {final_null} rows still have NULL datetime_utc8")
    
    # Show sample data
    print()
    print("Sample data (first 5 rows):")
    cursor.execute("""
        SELECT timestamp, datetime_utc8, pair, timeframe
        FROM candles
        ORDER BY id
        LIMIT 5
    """)
    samples = cursor.fetchall()
    for ts, dt, pair, tf in samples:
        print(f"  {ts} -> {dt} ({pair} {tf})")
    
    conn.close()


if __name__ == "__main__":
    run_migration()
```

- [ ] **Step 2: Test migration script with dry-run logic**

Add a `--dry-run` option for safe testing. Update the script:

```python
#!/usr/bin/env python3
"""Database migration script: Add datetime_utc8 field to candles table.

This script:
1. Adds the datetime_utc8 TEXT column to the candles table
2. Migrates all existing rows (218,900+) by calculating UTC+8 datetime strings
3. Uses batch processing to avoid memory issues
"""

import sys
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.datetime_utils import convert_to_utc8_str


# Database path
DB_PATH = Path("data/cryptoquant.db")
BATCH_SIZE = 1000


def add_datetime_utc8_column(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Add datetime_utc8 column if it doesn't exist.
    
    Args:
        conn: SQLite database connection
        dry_run: If True, don't execute ALTER TABLE
    """
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(candles)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'datetime_utc8' not in columns:
        if dry_run:
            print("[DRY-RUN] Would add datetime_utc8 column")
        else:
            print("Adding datetime_utc8 column...")
            cursor.execute("ALTER TABLE candles ADD COLUMN datetime_utc8 TEXT")
            conn.commit()
            print("✓ Column added successfully")
    else:
        print("✓ datetime_utc8 column already exists")


def migrate_batch(conn: sqlite3.Connection, batch_num: int, dry_run: bool = False) -> int:
    """Migrate a batch of rows with NULL datetime_utc8.
    
    Args:
        conn: SQLite database connection
        batch_num: Current batch number for logging
        dry_run: If True, don't execute UPDATE
        
    Returns:
        Number of rows that would be migrated
    """
    cursor = conn.cursor()
    
    # Fetch rows with NULL datetime_utc8
    cursor.execute("""
        SELECT id, timestamp FROM candles
        WHERE datetime_utc8 IS NULL
        LIMIT ?
    """, (BATCH_SIZE,))
    
    rows = cursor.fetchall()
    
    if not rows:
        return 0
    
    if dry_run:
        # Just log what would happen
        print(f"[DRY-RUN] Batch {batch_num}: Would migrate {len(rows)} rows")
        return len(rows)
    
    # Update each row
    for row_id, timestamp in rows:
        utc8_str = convert_to_utc8_str(timestamp)
        cursor.execute("""
            UPDATE candles
            SET datetime_utc8 = ?
            WHERE id = ?
        """, (utc8_str, row_id))
    
    conn.commit()
    
    return len(rows)


def run_migration(dry_run: bool = False) -> None:
    """Execute the full migration process.
    
    Args:
        dry_run: If True, show what would happen without making changes
    """
    mode = "[DRY-RUN]" if dry_run else ""
    print("="*60)
    print(f"{mode} Database Migration: Add datetime_utc8 field")
    print("="*60)
    print(f"Database: {DB_PATH}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Mode: {'Dry-run (no changes)' if dry_run else 'Live migration'}")
    print()
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    
    # Step 1: Add column
    add_datetime_utc8_column(conn, dry_run)
    print()
    
    # Check current state
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
    null_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM candles")
    total_count = cursor.fetchone()[0]
    
    print(f"Total rows: {total_count}")
    print(f"Rows needing migration: {null_count}")
    print()
    
    if null_count == 0:
        print("✓ All rows already migrated, nothing to do")
        conn.close()
        return
    
    # Step 2: Migrate in batches
    print(f"{mode} Starting batch migration...")
    batch_num = 0
    migrated_total = 0
    
    while True:
        batch_num += 1
        migrated = migrate_batch(conn, batch_num, dry_run)
        
        if migrated == 0:
            break
        
        migrated_total += migrated
        
        # Progress logging every 10 batches or in dry-run
        if dry_run or batch_num % 10 == 0:
            cursor.execute("SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL")
            remaining = cursor.fetchone()[0]
            print(f"{mode} Batch {batch_num}: Migrated {migrated} rows "
                  f"(Total: {migrated_total}, Remaining: {remaining})")
        
        # In dry-run, only process first batch
        if dry_run:
            print(f"{mode} Dry-run complete, stopping after first batch")
            break
    
    print()
    print("="*60)
    print(f"{mode} Migration Summary")
    print("="*60)
    print(f"Total batches processed: {batch_num}")
    print(f"Total rows that would be migrated: {migrated_total}")
    
    # Show sample conversion
    print()
    print(f"{mode} Sample conversions:")
    cursor.execute("""
        SELECT id, timestamp FROM candles
        WHERE datetime_utc8 IS NULL
        LIMIT 5
    """)
    samples = cursor.fetchall()
    for row_id, timestamp in samples:
        utc8_str = convert_to_utc8_str(timestamp)
        print(f"  Row {row_id}: {timestamp} -> '{utc8_str}'")
    
    conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Add datetime_utc8 field to candles table"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)
```

- [ ] **Step 3: Run migration script in dry-run mode**

Run: `python scripts/migrate_add_datetime_utc8.py --dry-run`
Expected: Shows what would happen without making changes

- [ ] **Step 4: Run actual migration**

Run: `python scripts/migrate_add_datetime_utc8.py`
Expected: Successfully migrates all 218,900 rows

- [ ] **Step 5: Verify migration results**

Run: `python -c "
import sqlite3
conn = sqlite3.connect('data/cryptoquant.db')
cursor = conn.cursor()

# Check NULL count
cursor.execute('SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL')
null_count = cursor.fetchone()[0]
print(f'NULL datetime_utc8: {null_count}')

# Check total
cursor.execute('SELECT COUNT(*) FROM candles')
total = cursor.fetchone()[0]
print(f'Total rows: {total}')

# Sample data
cursor.execute('SELECT timestamp, datetime_utc8 FROM candles LIMIT 5')
samples = cursor.fetchall()
print('Sample conversions:')
for ts, dt in samples:
    print(f'  {ts} -> {dt}')

conn.close()
"`
Expected: 
- NULL count: 0
- Total rows: 218900+
- Sample conversions show correct format

- [ ] **Step 6: Commit migration script**

```bash
git add scripts/migrate_add_datetime_utc8.py
git commit -m "feat: add database migration script for datetime_utc8 field"
```

---

## Task 3: Modify fetch_data_simple.py to populate datetime_utc8

**Files:**
- Modify: `scripts/fetch_data_simple.py:138-169`

- [ ] **Step 1: Add import for datetime_utils**

Locate line 12 in `scripts/fetch_data_simple.py` (imports section). Add:

```python
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from scripts.utils.datetime_utils import convert_to_utc8_str  # NEW
```

- [ ] **Step 2: Modify save_candles_to_db function**

Locate function `save_candles_to_db` (lines 138-169). Update INSERT statement:

```python
def save_candles_to_db(candles: list, pair: str, timeframe: str):
    """Save candles to database."""
    if not candles:
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    inserted = 0
    for candle in candles:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO candles
                (timestamp, datetime_utc8, open, high, low, close, volume, pair, timeframe)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candle["timestamp"],
                convert_to_utc8_str(candle["timestamp"]),  # NEW
                float(candle["open"]),
                float(candle["high"]),
                float(candle["low"]),
                float(candle["close"]),
                float(candle["volume"]),
                candle["pair"],
                candle["timeframe"],
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting candle: {e}")

    conn.commit()
    conn.close()
    return inserted
```

- [ ] **Step 3: Test modified script**

Run: `python scripts/fetch_data_simple.py --timeframe 1h --days 1`
Expected: Fetches new data and verifies datetime_utc8 is populated

- [ ] **Step 4: Verify new data has datetime_utc8**

Run: `python -c "
import sqlite3
conn = sqlite3.connect('data/cryptoquant.db')
cursor = conn.cursor()

# Get latest 5 rows
cursor.execute('SELECT timestamp, datetime_utc8 FROM candles ORDER BY id DESC LIMIT 5')
rows = cursor.fetchall()
print('Latest 5 rows:')
for ts, dt in rows:
    print(f'  {ts} -> {dt}')

# Check for NULL in recent rows
cursor.execute('SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL AND id > (SELECT MAX(id) - 100 FROM candles)')
null_recent = cursor.fetchone()[0]
print(f'NULL in recent 100 rows: {null_recent}')

conn.close()
"`
Expected: All recent rows have datetime_utc8 values

- [ ] **Step 5: Commit modified fetch script**

```bash
git add scripts/fetch_data_simple.py
git commit -m "feat: update fetch_data_simple.py to populate datetime_utc8"
```

---

## Task 4: Modify fetch_continuous.py to populate datetime_utc8

**Files:**
- Modify: `scripts/fetch_continuous.py`

- [ ] **Step 1: Read file to understand structure**

Run: Read the file to find INSERT statement location.

- [ ] **Step 2: Add import for datetime_utils**

Add at top of imports section:

```python
from scripts.utils.datetime_utils import convert_to_utc8_str
```

- [ ] **Step 3: Modify INSERT statement**

Find the INSERT statement in the save function and add datetime_utc8 field:

```python
cursor.execute("""
    INSERT OR REPLACE INTO candles
    (timestamp, datetime_utc8, open, high, low, close, volume, pair, timeframe)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    candle["timestamp"],
    convert_to_utc8_str(candle["timestamp"]),  # NEW
    float(candle["open"]),
    float(candle["high"]),
    float(candle["low"]),
    float(candle["close"]),
    float(candle["volume"]),
    candle["pair"],
    candle["timeframe"],
))
```

- [ ] **Step 4: Commit modified script**

```bash
git add scripts/fetch_continuous.py
git commit -m "feat: update fetch_continuous.py to populate datetime_utc8"
```

---

## Task 5: Modify fetch_all_data.py to populate datetime_utc8

**Files:**
- Modify: `scripts/fetch_all_data.py`

- [ ] **Step 1: Read file to understand structure**

Run: Read the file to find INSERT statement location.

- [ ] **Step 2: Add import for datetime_utils**

Add at top of imports section:

```python
from scripts.utils.datetime_utils import convert_to_utc8_str
```

- [ ] **Step 3: Modify INSERT statement**

Find the INSERT statement and add datetime_utc8 field (same pattern as previous tasks).

- [ ] **Step 4: Commit modified script**

```bash
git add scripts/fetch_all_data.py
git commit -m "feat: update fetch_all_data.py to populate datetime_utc8"
```

---

## Task 6: Final integration test and verification

**Files:**
- Test: Database verification

- [ ] **Step 1: Run comprehensive verification**

Run: `python -c "
import sqlite3
from pathlib import Path

DB_PATH = Path('data/cryptoquant.db')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print('='*60)
print('FINAL VERIFICATION')
print('='*60)

# Total row count
cursor.execute('SELECT COUNT(*) FROM candles')
total = cursor.fetchone()[0]
print(f'Total rows: {total}')

# NULL check
cursor.execute('SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL')
null_count = cursor.fetchone()[0]
print(f'Rows with NULL datetime_utc8: {null_count}')

# Sample conversions (random 10 rows)
cursor.execute('SELECT timestamp, datetime_utc8 FROM candles ORDER BY RANDOM() LIMIT 10')
samples = cursor.fetchall()
print()
print('Random sample conversions:')
for ts, dt in samples:
    print(f'  {ts} -> {dt}')

# Time range check
cursor.execute('SELECT MIN(timestamp), MAX(timestamp) FROM candles')
min_ts, max_ts = cursor.fetchone()
print()
print(f'Time range: {min_ts} to {max_ts}')

# Conversion verification
from scripts.utils.datetime_utils import convert_to_utc8_str
print()
print('Manual conversion verification:')
cursor.execute('SELECT timestamp FROM candles LIMIT 1')
sample_ts = cursor.fetchone()[0]
converted = convert_to_utc8_str(sample_ts)
cursor.execute('SELECT datetime_utc8 FROM candles WHERE timestamp = ?', (sample_ts,))
stored = cursor.fetchone()[0]
print(f'  Timestamp: {sample_ts}')
print(f'  Calculated: {converted}')
print(f'  Stored: {stored}')
print(f'  Match: {converted == stored}')

conn.close()
print()
print('='*60)
print('✓ VERIFICATION COMPLETE')
print('='*60)
"`

Expected:
- Total rows: 218900+
- NULL datetime_utc8: 0
- Sample conversions show correct format
- Manual conversion matches stored value

- [ ] **Step 2: Run all tests**

Run: `pytest tests/test_datetime_conversion.py -v`
Expected: All 5 tests pass

- [ ] **Step 3: Final commit message**

```bash
git status
# Verify all modified files are committed

# If any uncommitted changes:
git add -A
git commit -m "feat: complete datetime_utc8 field implementation"
```

---

## Success Criteria Checklist

- [ ] Utility module created and tested (5 tests passing)
- [ ] Migration script executed successfully (0 NULL values remaining)
- [ ] All fetch scripts modified to populate datetime_utc8
- [ ] New data contains correct datetime_utc8 values
- [ ] All commits made with appropriate messages

---

## Notes

- **Data integrity**: The migration script uses batch processing with commits after each batch, ensuring partial progress is saved even if interrupted.
- **Rollback**: SQLite doesn't support dropping columns easily. If rollback needed, create new table without the column and copy data.
- **Performance**: Batch size of 1000 rows balances memory usage and commit frequency. Adjust if needed.
- **Testing**: Always run migration script with `--dry-run` first to preview actions.