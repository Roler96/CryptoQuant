"""Engine state persistence — JSON with checksum."""
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger


@dataclass
class EngineState:
    """Engine state snapshot."""

    timestamp: int
    strategy_name: str
    symbol: str
    balance: float
    initial_capital: float
    has_position: bool
    position_side: str
    position_entry_price: float
    position_amount: float
    position_entry_time: int
    active_order_ids: list[str]
    total_trades: int
    total_pnl_pct: float
    last_signal: int
    last_tick_time: int


class StateManager:
    """State persistence with atomic write + SHA-256 checksum."""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, strategy_name: str, symbol: str) -> Path:
        safe_symbol = symbol.replace("/", "_").lower()
        return self.state_dir / f"state_{strategy_name}_{safe_symbol}.json"

    def save(self, state: EngineState) -> None:
        path = self._state_path(state.strategy_name, state.symbol)
        tmp_path = path.with_suffix(".tmp")
        data = asdict(state)

        json_str = json.dumps(data, indent=2)
        checksum = _sha256(json_str)

        data["saved_at"] = datetime.now(UTC).isoformat()
        data["checksum"] = checksum

        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        tmp_path.rename(path)

    def load(self, strategy_name: str, symbol: str) -> EngineState | None:
        path = self._state_path(strategy_name, symbol)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)

        stored_checksum = data.pop("checksum", None)
        if stored_checksum:
            payload = {k: v for k, v in data.items() if k != "saved_at"}
            expected_json = json.dumps(payload, indent=2)
            if _sha256(expected_json) != stored_checksum:
                logger.error(
                    f"State file checksum mismatch for {strategy_name}/{symbol}, "
                    f"file may be corrupted. Starting fresh."
                )
                return None

        try:
            return EngineState(**{k: v for k, v in data.items() if k != "saved_at"})
        except (TypeError, ValueError) as e:
            logger.error(f"State file parse error: {e}. Starting fresh.")
            return None


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()
