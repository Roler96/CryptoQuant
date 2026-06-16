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


class TestBackupRotation:
    def test_backup_rotation_creates_versions(self, state_mgr, sample_state):
        for i in range(7):
            state = EngineState(
                timestamp=1704067200000 + i,
                strategy_name="TestStrategy",
                symbol="BTC/USDT",
                balance=10000.0 + i,
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
            state_mgr.save(state)

        base_path = state_mgr._state_path("TestStrategy", "BTC/USDT")
        assert base_path.exists()
        for v in range(1, StateManager.MAX_BACKUPS):
            backup = state_mgr._backup_path(base_path, v)
            assert backup.exists()

    def test_load_uses_v0_first(self, state_mgr, sample_state):
        state_mgr.save(sample_state)
        loaded = state_mgr.load("TestStrategy", "BTC/USDT")
        assert loaded is not None
        assert loaded.balance == 10000.0

    def test_load_falls_back_to_v1_on_corruption(self, state_mgr, sample_state, tmp_path):
        state_mgr.save(sample_state)
        new_state = EngineState(
            timestamp=1704067200001,
            strategy_name="TestStrategy",
            symbol="BTC/USDT",
            balance=20000.0,
            initial_capital=10000.0,
            has_position=False,
            position_side="",
            position_entry_price=0.0,
            position_amount=0.0,
            position_entry_time=0,
            active_order_ids=[],
            total_trades=10,
            total_pnl_pct=5.0,
            last_signal=0,
            last_tick_time=1704067200001,
        )
        state_mgr.save(new_state)
        base_path = tmp_path / "state_TestStrategy_btc_usdt.json"

        with open(base_path) as f:
            data = f.read()
        with open(base_path, "w") as f:
            f.write(data.replace("20000.0", "99999.0"))

        loaded = state_mgr.load("TestStrategy", "BTC/USDT")
        assert loaded is not None
        assert loaded.balance == 10000.0

    def test_load_falls_back_through_all_versions(self, state_mgr, sample_state, tmp_path):
        for i in range(StateManager.MAX_BACKUPS):
            state = EngineState(
                timestamp=1704067200000 + i,
                strategy_name="TestStrategy",
                symbol="BTC/USDT",
                balance=10000.0 + i,
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
                last_tick_time=1704067200000 + i,
            )
            state_mgr.save(state)

        base_path = tmp_path / "state_TestStrategy_btc_usdt.json"

        for v in range(StateManager.MAX_BACKUPS):
            backup_path = state_mgr._backup_path(base_path, v)
            with open(backup_path) as f:
                data = f.read()
            with open(backup_path, "w") as f:
                f.write(data.replace("10000.0", f"{99999.0 + v}"))

        loaded = state_mgr.load("TestStrategy", "BTC/USDT")
        assert loaded is None

    def test_backup_content_preserved(self, state_mgr, sample_state):
        state_mgr.save(sample_state)

        new_state = EngineState(
            timestamp=1704067200001,
            strategy_name="TestStrategy",
            symbol="BTC/USDT",
            balance=20000.0,
            initial_capital=10000.0,
            has_position=False,
            position_side="",
            position_entry_price=0.0,
            position_amount=0.0,
            position_entry_time=0,
            active_order_ids=[],
            total_trades=10,
            total_pnl_pct=5.0,
            last_signal=0,
            last_tick_time=1704067200001,
        )
        state_mgr.save(new_state)

        base_path = state_mgr._state_path("TestStrategy", "BTC/USDT")
        v1_path = state_mgr._backup_path(base_path, 1)
        with open(v1_path) as f:
            data = f.read()
        assert "10000.0" in data
        assert "total_trades\": 5" in data

    def test_max_backups_constant(self):
        assert StateManager.MAX_BACKUPS == 5
