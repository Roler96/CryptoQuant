"""The calibration gate must be a comparison, not a printed sentence.

A gate that prints FAILED and exits zero fails open: every CI job, cron and
`&&` chain downstream of it reads success, which is the state the gate exists
to prevent.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "calibrate_donchian.py"


def load_script():
    spec = importlib.util.spec_from_file_location("calibrate_donchian", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeMetrics:
    def __init__(self, total_return, sharpe, max_drawdown, trades):
        self.total_return = total_return
        self.sharpe = sharpe
        self.max_drawdown = max_drawdown
        self.trades = trades


@pytest.fixture(scope="module")
def gate():
    return load_script()


def test_a_run_matching_the_baseline_reports_no_deviation(gate):
    baseline = gate.BASELINE
    matching = FakeMetrics(
        baseline["return"], baseline["sharpe"], baseline["max_drawdown"], baseline["trades"]
    )
    assert gate._deviations(matching) == []


def test_the_deviation_names_the_figure_and_the_size_of_the_miss(gate):
    # The number the gate is actually closed over: 1,053% against a 17.47x
    # baseline is not a rounding difference and must be said out loud.
    way_off = FakeMetrics(10.53, 0.69, 0.778, 54)

    deviations = gate._deviations(way_off)

    assert len(deviations) == 1
    assert "return" in deviations[0]
    assert "tolerance" in deviations[0]


def test_each_baseline_figure_is_actually_compared(gate):
    baseline = gate.BASELINE
    for name, value in (
        ("sharpe", baseline["sharpe"] + 1.0),
        ("max_drawdown", baseline["max_drawdown"] + 0.5),
        ("trades", baseline["trades"] * 3),
    ):
        metrics = FakeMetrics(
            baseline["return"], baseline["sharpe"], baseline["max_drawdown"], baseline["trades"]
        )
        setattr(metrics, "total_return" if name == "return" else name, value)
        assert any(name in line for line in gate._deviations(metrics)), name


def test_a_miss_inside_tolerance_is_not_a_failure(gate):
    baseline = gate.BASELINE
    close_enough = FakeMetrics(
        baseline["return"] * 1.1,  # 10%, inside the 25% relative tolerance
        baseline["sharpe"] + 0.10,
        baseline["max_drawdown"] + 0.05,
        int(baseline["trades"] * 1.2),
    )
    assert gate._deviations(close_enough) == []


def test_the_script_exits_non_zero_when_it_cannot_run(tmp_path, monkeypatch, capsys):
    # No database, so no comparison happened. That is not a pass either.
    monkeypatch.chdir(tmp_path)
    gate = load_script()

    assert gate.main() == 1
    assert "no data" in capsys.readouterr().out


def test_a_closed_gate_exits_non_zero(tmp_path, monkeypatch, capsys):
    # The defect this pins: the script printed "GATE: FAILED" and exited 0, so
    # every `&&`, cron and CI step downstream of it read success. A gate that
    # fails open is worse than no gate, because it is documented as one.
    from cq.data.store import Store
    from cq.research.split import to_ms

    hour = 3_600_000
    start = to_ms("2021-01-01")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    with Store(tmp_path / "data" / "cq.db") as store:
        # A flat market: Donchian never breaks out, so the run returns 0% and
        # is nowhere near the +1,747% baseline.
        store.upsert_ohlcv(
            [
                ("DOGE-USDT-SWAP", "1h", start + i * hour, 1.0, 1.0, 1.0, 1.0, 100.0, 100.0)
                for i in range(3_000)
            ]
        )

    gate = load_script()
    code = gate.main()

    out = capsys.readouterr().out
    assert "GATE: FAILED" in out
    assert "return" in out, "the gate must say which figure missed"
    assert code == 1, "a closed gate that exits zero is not a gate"
