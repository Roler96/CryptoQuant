#!/usr/bin/env python
"""Docker health check for CryptoQuant live engine.

Checks freshness of state files. If the engine is alive, StateManager
saves state periodically. Stale or absent state files indicate a stuck
or dead engine.

Exit codes: 0 = healthy, 1 = unhealthy.
"""
import os
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("CQ_STATE_DIR", "/app/state"))
MAX_STALE_SECONDS = 600  # 10 min — state saves more frequently than this


def main() -> int:
    if not STATE_DIR.exists():
        print(f"FAIL: state directory {STATE_DIR} does not exist")
        return 1

    state_files = list(STATE_DIR.glob("state_*.json"))
    if not state_files:
        print(f"FAIL: no state files in {STATE_DIR}")
        return 1

    latest_mtime = max(f.stat().st_mtime for f in state_files)
    age = time.time() - latest_mtime

    if age > MAX_STALE_SECONDS:
        print(f"FAIL: state file stale ({age:.0f}s old, limit {MAX_STALE_SECONDS}s)")
        return 1

    print(f"OK: state file updated {age:.0f}s ago")
    return 0


if __name__ == "__main__":
    sys.exit(main())
