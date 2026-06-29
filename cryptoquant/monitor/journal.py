"""Trade journal — JSONL format, thread-safe."""
from contextlib import contextmanager
import json
import os
from datetime import UTC, datetime
from pathlib import Path


class TradeJournal:
    """Trade journal — one trade per line in JSONL format.

    Thread-safe via file locking.
    """

    def __init__(self, journal_dir: str = "logs", strategy_name: str = "default"):
        safe_name = strategy_name.replace("/", "_").replace(" ", "_")
        self.journal_path = Path(journal_dir) / f"trade_journal_{safe_name}.jsonl"
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, trade_data: dict) -> None:
        """Append a trade record (thread-safe)."""
        record = dict(trade_data)
        record["recorded_at"] = datetime.now(UTC).isoformat()

        with open(self.journal_path, "a+", encoding="utf-8") as f:
            with _locked_file(f):
                f.seek(0, os.SEEK_END)
                f.write(json.dumps(record) + "\n")
                f.flush()

    def load_all(self) -> list[dict]:
        """Load all trade records."""
        if not self.journal_path.exists():
            return []
        trades = []
        with open(self.journal_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        return trades

    def stats(self) -> dict:
        """Trade statistics snapshot."""
        trades = self.load_all()
        if not trades:
            return {"total": 0}

        wins = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losses = [t for t in trades if t.get("pnl_pct", 0) <= 0]

        return {
            "total": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0,
            "total_pnl_pct": sum(t.get("pnl_pct", 0) for t in trades),
            "total_pnl_abs": sum(t.get("pnl_abs", 0) for t in trades),
            "avg_win": sum(t.get("pnl_pct", 0) for t in wins) / len(wins) if wins else 0,
            "avg_loss": (
                sum(t.get("pnl_pct", 0) for t in losses) / len(losses) if losses else 0
            ),
            "best_trade": max(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None,
            "worst_trade": min(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None,
        }


@contextmanager
def _locked_file(file_obj):
    """Lock a journal file across supported platforms."""
    if os.name == "nt":
        import msvcrt

        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
