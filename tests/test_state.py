"""Tests for StateManager."""
import pytest

from cryptoquant.engine.state import StateManager, EngineState


@pytest.fixture
def state_mgr(tmp_path):
    return StateManager(state_dir=str(tmp_path))


@pytest.fixture
def sample_state():
    return EngineState(
        timestamp=1704067200000,
        strategy_name="TestStrategy",
        symbol="BTC/USDT",
        balance=10000.0,
        initial_capital=10000.0,
        has_position=False,
        position_side="",
        position_entry_price=0.0,
        position_amount=0.0,
        position_entry_time=0,
        active_order_ids=[],
        total_trades=5,
        total_pnl_pct=2.5,
        last_signal=0,
        last_tick_time=1704067200000,
    )


class TestStateManager:
    def test_save_and_load(self, state_mgr, sample_state):
        state_mgr.save(sample_state)
        loaded = state_mgr.load("TestStrategy", "BTC/USDT")
        assert loaded is not None
        assert loaded.strategy_name == "TestStrategy"
        assert loaded.balance == 10000.0
        assert loaded.total_trades == 5

    def test_load_nonexistent(self, state_mgr):
        assert state_mgr.load("NonExistent", "BTC/USDT") is None

    def test_checksum_corruption(self, state_mgr, sample_state, tmp_path):
        state_mgr.save(sample_state)
        path = tmp_path / "state_TestStrategy_btc_usdt.json"
        with open(path) as f:
            data = f.read()
        with open(path, "w") as f:
            f.write(data.replace("10000.0", "99999.0"))
        loaded = state_mgr.load("TestStrategy", "BTC/USDT")
        assert loaded is None

    def test_atomic_write(self, state_mgr, sample_state):
        state_mgr.save(sample_state)
        tmp_files = list(state_mgr.state_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_state_dir_created(self, tmp_path):
        StateManager(state_dir=str(tmp_path / "new_dir"))
        assert (tmp_path / "new_dir").exists()
