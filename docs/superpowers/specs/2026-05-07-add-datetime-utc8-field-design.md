# Design: Add datetime_utc8 Field to Database

**Date**: 2026-05-07
**Status**: Draft
**Author**: Sisyphus

## Overview

Add a human-readable UTC+8 datetime string field (`datetime_utc8`) to the existing `candles` database table, positioned after the `timestamp` field. The field will display timestamps in `YYYY-MM-DD HH:MM:SS` format (UTC+8 timezone) for improved readability.

## Current State Analysis

### Database Schema

- **Active table**: `candles` (218,900 rows)
  - Schema: `id, timestamp (INTEGER), open, high, low, close, volume, pair, timeframe, created_at`
  - Managed by: `scripts/fetch_data_simple.py` and related fetch scripts
- **Inactive table**: `ohlcv_candles` (SQLAlchemy model, not used in production)

### Timestamp Handling

- Timestamp values: Milliseconds (Unix epoch)
- Source: OKX API via `int(candle[0])` in `manager.py`
- Current format: INTEGER, not human-readable

## Design

### 1. Table Structure Modification

**SQL modification**:
```sql
ALTER TABLE candles ADD COLUMN datetime_utc8 TEXT;
```

**Field specification**:
- Name: `datetime_utc8`
- Type: TEXT
- Position: After `timestamp` field (conceptual, SQLite doesn't enforce column order)
- Format: `YYYY-MM-DD HH:MM:SS`
- Example: `2026-05-07 21:34:25` (UTC+8 representation of timestamp `1746538080000`)
- Index: None (field is for display, queries use `timestamp`)

### 2. Data Migration Strategy

**Script**: `scripts/migrate_add_datetime_utc8.py`

**Migration approach**:
- Batch processing (1000 rows per batch) to avoid memory issues
- Process all 218,900 existing rows
- Target: Rows where `datetime_utc8 IS NULL`

**Migration logic**:
```python
from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))

def convert_to_utc8_str(timestamp_ms: int) -> str:
    """Convert millisecond timestamp to UTC+8 string.
    
    Args:
        timestamp_ms: Unix timestamp in milliseconds
        
    Returns:
        UTC+8 datetime string in format 'YYYY-MM-DD HH:MM:SS'
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC8)
    return dt.strftime('%Y-%m-%d %H:%M:%S')
```

**Migration steps**:
1. Open database connection
2. Loop until no rows with `datetime_utc8 IS NULL`:
   ```python
   SELECT id, timestamp FROM candles WHERE datetime_utc8 IS NULL LIMIT 1000
   for each row:
       utc8_str = convert_to_utc8_str(row.timestamp)
       UPDATE candles SET datetime_utc8 = utc8_str WHERE id = row.id
   ```
3. Commit after each batch
4. Report progress and completion

### 3. Code Modifications

**Files to modify**:

| File | Location | Change |
|------|----------|--------|
| `scripts/fetch_data_simple.py` | Line 149-153 (INSERT statement) | Add `datetime_utc8` field and value |
| `scripts/fetch_continuous.py` | INSERT statement | Add `datetime_utc8` field and value |
| `scripts/fetch_all_data.py` | INSERT statement | Add `datetime_utc8` field and value |
| Other fetch scripts | INSERT statements | Add `datetime_utc8` field and value |

**Modification pattern** (example for `fetch_data_simple.py`):

Before:
```python
cursor.execute("""
    INSERT OR REPLACE INTO candles
    (timestamp, open, high, low, close, volume, pair, timeframe)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", (
    candle["timestamp"],
    float(candle["open"]),
    float(candle["high"]),
    float(candle["low"]),
    float(candle["close"]),
    float(candle["volume"]),
    candle["pair"],
    candle["timeframe"],
))
```

After:
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

**Helper function placement**:
- Add `convert_to_utc8_str()` to each fetch script (minimal duplication, scripts are independent)
- Alternative: Create shared utility module `scripts/utils/datetime_utils.py` if future needs arise

### 4. Verification and Testing

**Migration verification**:
```bash
# Run migration
python scripts/migrate_add_datetime_utc8.py

# Check for NULL values
sqlite3 data/cryptoquant.db "SELECT COUNT(*) FROM candles WHERE datetime_utc8 IS NULL;"
# Expected: 0

# Verify time conversion accuracy
sqlite3 data/cryptoquant.db "SELECT timestamp, datetime_utc8 FROM candles LIMIT 5;"
# Expected:
# 1746538080000|2026-05-06 21:28:00
```

**Unit tests**: `tests/test_datetime_conversion.py`

```python
import pytest
from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))

def convert_to_utc8_str(timestamp_ms: int) -> str:
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC8)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def test_convert_known_timestamp():
    """Test conversion of known timestamp."""
    ts = 1746538080000  # 2026-05-06 13:28:00 UTC
    result = convert_to_utc8_str(ts)
    assert result == "2026-05-06 21:28:00"  # UTC+8 = 21:28

def test_convert_epoch():
    """Test Unix epoch conversion."""
    ts = 0
    result = convert_to_utc8_str(ts)
    assert result == "1970-01-01 08:00:00"  # UTC+8

def test_format_consistency():
    """Test output format is consistent."""
    ts = int(datetime.now().timestamp() * 1000)
    result = convert_to_utc8_str(ts)
    assert len(result) == 19  # YYYY-MM-DD HH:MM:SS
    assert " " in result
    assert "-" in result
    assert ":" in result
```

**Integration test**:
- After modifying fetch scripts, run data fetch once
- Verify new rows contain correct `datetime_utc8` values
- Query: `SELECT timestamp, datetime_utc8 FROM candles ORDER BY id DESC LIMIT 5;`

## Implementation Order

1. **Create migration script** (`scripts/migrate_add_datetime_utc8.py`)
2. **Run migration** (process existing 218,900 rows)
3. **Modify fetch scripts** (add datetime_utc8 to INSERT statements)
4. **Run unit tests** (verify conversion logic)
5. **Test with new data** (fetch small batch and verify)

## Scope

**In scope**:
- `candles` table modification
- Existing fetch scripts (`fetch_data_simple.py`, `fetch_continuous.py`, `fetch_all_data.py`)
- Data migration for existing 218,900 rows
- Unit tests for conversion function

**Out of scope**:
- `ohlcv_candles` table (not used in production)
- Parquet storage (file-based storage)
- Database query optimization
- CLI query tools modification

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Migration script fails midway | Incomplete data, NULL values remain | Batch commits, progress logging, can rerun |
| Incorrect UTC+8 calculation | Wrong datetime strings | Unit tests, manual verification with known timestamps |
| Breaking existing queries | Queries expecting specific column count | Use `INSERT OR REPLACE` preserves existing behavior, new field is last |

## Success Criteria

- ✅ All 218,900 rows have non-NULL `datetime_utc8` values
- ✅ `datetime_utc8` values match expected UTC+8 time (verified manually)
- ✅ New data fetches include correct `datetime_utc8` values
- ✅ Unit tests pass
- ✅ No regression in existing data fetch scripts

## References

- Database schema: `data/cryptoquant.db` (candles table)
- Data insertion: `scripts/fetch_data_simple.py:138-169`
- Timestamp source: OKX API via `int(candle[0])` (milliseconds)