"""Tests for latency models."""

from cryptoquant.engine.latency import RandomLatency, ZeroLatency


class TestZeroLatency:
    def test_always_zero(self):
        model = ZeroLatency()
        assert model.bars_delay() == 0


class TestRandomLatency:
    def test_within_bounds(self):
        model = RandomLatency(min_bars=1, max_bars=3, seed=42)
        for _ in range(100):
            delay = model.bars_delay()
            assert 1 <= delay <= 3

    def test_reproducible_with_seed(self):
        model_a = RandomLatency(min_bars=0, max_bars=5, seed=123)
        model_b = RandomLatency(min_bars=0, max_bars=5, seed=123)
        delays_a = [model_a.bars_delay() for _ in range(20)]
        delays_b = [model_b.bars_delay() for _ in range(20)]
        assert delays_a == delays_b

    def test_zero_min_max(self):
        model = RandomLatency(min_bars=0, max_bars=0, seed=42)
        assert model.bars_delay() == 0
