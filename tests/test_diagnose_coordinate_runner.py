import json

import numpy as np
import pandas as pd
import pytest

import scripts.diagnose_coordinate as diagnose_coordinate
from cq.research.split import ProtocolError
from scripts.diagnose_coordinate import assert_contiguous, fingerprint, main, run

BAR_MS = 300_000


def _contiguous_frame(days: int) -> pd.DataFrame:
    n = days * 288
    index = pd.to_datetime(np.arange(n) * BAR_MS, unit="ms", utc=True)
    return pd.DataFrame(
        {
            "open": np.ones(n),
            "high": np.ones(n),
            "low": np.ones(n),
            "close": np.ones(n),
            "volume": np.ones(n),
            "quote_volume": np.ones(n),
        },
        index=index,
    )


def test_contiguous_frame_is_accepted():
    assert_contiguous(_contiguous_frame(3))


def test_missing_bar_is_refused_rather_than_interpolated():
    frame = _contiguous_frame(3).drop(index=_contiguous_frame(3).index[100])
    with pytest.raises(ProtocolError, match="contiguous"):
        assert_contiguous(frame)


def test_fingerprint_is_stable_and_sensitive():
    frame = _contiguous_frame(1)
    assert fingerprint(frame) == fingerprint(frame.copy())
    altered = frame.copy()
    altered.iloc[0, altered.columns.get_loc("close")] = 2.0
    assert fingerprint(altered) != fingerprint(frame)


def test_expected_bars_matching_is_accepted():
    frame = _contiguous_frame(3)
    assert_contiguous(frame, expected_bars=3 * 288)


def test_truncated_window_passes_internal_check_but_fails_expected_bars():
    # Dropping the tail row leaves a frame that is still internally contiguous
    # -- span and count are both derived from the frame's own first/last
    # timestamp, so a truncated window is self-consistent and the bare call
    # accepts it. Only the explicit expected_bars catches that the requested
    # window was not actually delivered in full.
    frame = _contiguous_frame(3).iloc[:-1]
    assert_contiguous(frame)
    with pytest.raises(ProtocolError, match="expected"):
        assert_contiguous(frame, expected_bars=3 * 288)


def _synthetic_ohlcv(days: int, seed: int = 0) -> pd.DataFrame:
    """A small, strictly-positive, non-degenerate OHLCV series for smoke tests.

    Prices are a log-random-walk (never touches zero over the relevant
    horizon) and turnover is lognormal, so every upstream guard (positive
    prices, high >= low, positive turnover, non-zero null variance) is
    satisfied without special-casing.
    """
    n = days * 288
    rng = np.random.default_rng(seed)
    index = pd.to_datetime(np.arange(n) * BAR_MS, unit="ms", utc=True)
    log_price = np.cumsum(rng.normal(0.0, 0.0015, size=n))
    close = 100.0 * np.exp(log_price)
    open_ = np.concatenate(([close[0]], close[:-1]))
    wiggle = np.abs(rng.normal(0.0, 0.0008, size=n)) * close + 1e-6
    high = np.maximum(open_, close) + wiggle
    low = np.maximum(np.minimum(open_, close) - wiggle, 1e-3)
    volume = rng.lognormal(mean=10.0, sigma=1.0, size=n)
    quote_volume = volume * close
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": quote_volume,
        },
        index=index,
    )


@pytest.fixture
def _shrunk_window(monkeypatch):
    """Shrink the explore window and draw count so run() finishes in seconds.

    `EXPLORE_END` is set exactly `days` calendar days after `EXPLORE_START` so
    the window's bar count (used by run()'s expected_bars check) matches the
    synthetic frame's length exactly -- day boundaries divide evenly into 5m
    bars, so this is exact, not approximate.
    """
    days = 40
    monkeypatch.setattr(diagnose_coordinate, "EXPLORE_START", "2021-01-01")
    end = (pd.Timestamp("2021-01-01", tz="UTC") + pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    monkeypatch.setattr(diagnose_coordinate, "EXPLORE_END", end)
    monkeypatch.setattr(diagnose_coordinate, "DRAWS", 20)
    return days


def _patch_store_load(monkeypatch, frame: pd.DataFrame) -> None:
    def _fake_load_ohlcv(self, inst_id, timeframe, start_ms=None, end_ms=None):
        return frame

    monkeypatch.setattr(diagnose_coordinate.Store, "load_ohlcv", _fake_load_ohlcv)


def test_run_end_to_end_smoke(monkeypatch, tmp_path, _shrunk_window):
    """`run()` on synthetic data: no real DB, no real diagnosis, just plumbing.

    This is the guard the module's own comments call for: nothing here checks
    that a *value* is right (that would be flaky on random data), only that
    the alignment invariant holds and the whole pipeline produces a
    JSON-serialisable, structurally complete result. If `aligned` were ever
    swapped back for `frame` anywhere downstream, `bars_aligned == bars - 1`
    or one of the `calendar_bars` checks would catch it.
    """
    days = _shrunk_window
    frame = _synthetic_ohlcv(days)
    _patch_store_load(monkeypatch, frame)

    out_path = tmp_path / "out.json"
    result = run(str(tmp_path / "smoke.db"), out_path)

    json.dumps(result, allow_nan=False)  # must not raise

    assert result["verdict"] in {"PASS", "CLOSED", "INVALID"}
    assert result["bars_aligned"] == result["bars"] - 1
    assert result["holdout_recorded"] is False
    for key in ("fidelity", "measures", "corroboration", "coupling_premise", "gates"):
        assert key in result
    for label, factor in diagnose_coordinate.SCALES.items():
        assert result["fidelity"][label]["calendar_bars"] == result["bars_aligned"] // factor

    assert out_path.exists()
    on_disk = json.loads(out_path.read_text())
    assert on_disk == result


def test_main_end_to_end_smoke(monkeypatch, tmp_path, capsys, _shrunk_window):
    """`main()` wires argv -> run() -> stdout + file; wiring is untested otherwise."""
    frame = _synthetic_ohlcv(_shrunk_window, seed=1)
    _patch_store_load(monkeypatch, frame)

    out_path = tmp_path / "main_out.json"
    exit_code = main(["--db", str(tmp_path / "smoke_main.db"), "--out", str(out_path)])

    assert exit_code == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["verdict"] in {"PASS", "CLOSED", "INVALID"}

    captured = capsys.readouterr()
    assert "verdict=" in captured.out
