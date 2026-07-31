"""Offline HTML report rendering for a persisted backtest run bundle."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from cq.backtest.render import RunBundleError, load_bundle
from cq.cli import main
from cq.core.clock import HOUR_MS
from cq.data.store import Store

DAY0 = 1_609_459_200_000


def _store_closes(db, inst_id: str, closes: Sequence[float]) -> None:
    with Store(db) as store:
        store.upsert_ohlcv(
            (
                inst_id,
                "1h",
                DAY0 + index * HOUR_MS,
                close,
                close,
                close,
                close,
                100.0,
                None,
            )
            for index, close in enumerate(closes)
        )


def _build_run_dir(tmp_path, capsys):
    db = tmp_path / "cq.db"
    output_dir = tmp_path / "reports"
    closes = [10, 10, 10, 10, 10, 11, 12, 13, 20, 19, 18, 17, 5, 6, 6, 6]
    _store_closes(db, "DOGE-USDT", closes)

    exit_code = main(
        [
            "backtest",
            "donchian",
            "--db",
            str(db),
            "--inst",
            "DOGE-USDT",
            "--lookback",
            "3",
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    capsys.readouterr()
    return next(output_dir.iterdir())


def test_load_bundle_reads_all_four_files(tmp_path, capsys):
    run_dir = _build_run_dir(tmp_path, capsys)

    bundle = load_bundle(run_dir)

    assert bundle.run_dir == run_dir
    assert bundle.summary["run_id"] == run_dir.name
    assert bundle.trades
    assert bundle.equity
    assert {row["segment"] for row in bundle.equity} == {"historical", "recent", "full"}


def test_load_bundle_rejects_a_run_dir_missing_equity_csv(tmp_path, capsys):
    run_dir = _build_run_dir(tmp_path, capsys)
    (run_dir / "equity.csv").unlink()

    with pytest.raises(RunBundleError, match="equity.csv"):
        load_bundle(run_dir)


def test_load_bundle_rejects_a_run_dir_missing_summary_json(tmp_path, capsys):
    run_dir = _build_run_dir(tmp_path, capsys)
    (run_dir / "summary.json").unlink()

    with pytest.raises(RunBundleError, match="summary.json"):
        load_bundle(run_dir)


from cq.backtest.render import SEGMENT_NAMES, build_chart_series, load_bundle


def test_build_chart_series_covers_all_three_segments(tmp_path, capsys):
    bundle = load_bundle(_build_run_dir(tmp_path, capsys))

    series = build_chart_series(bundle)

    assert set(series) == set(SEGMENT_NAMES)
    historical = series["historical"]
    assert len(historical.timestamps) == bundle.summary["segments"]["historical"]["metrics"]["bars"]
    assert len(historical.strategy_equity) == len(historical.timestamps)
    assert len(historical.benchmark_equity) == len(historical.timestamps)
    assert len(historical.strategy_drawdown) == len(historical.timestamps)
    assert historical.timestamps == sorted(historical.timestamps)


def test_build_chart_series_drawdown_matches_reported_max_drawdown(tmp_path, capsys):
    bundle = load_bundle(_build_run_dir(tmp_path, capsys))

    series = build_chart_series(bundle)

    for segment in SEGMENT_NAMES:
        reported = bundle.summary["segments"][segment]["metrics"]["max_drawdown"]
        computed = min(series[segment].strategy_drawdown, default=0.0)
        assert computed == pytest.approx(reported)


def test_build_chart_series_places_filled_trades_on_the_strategy_curve(tmp_path, capsys):
    bundle = load_bundle(_build_run_dir(tmp_path, capsys))

    series = build_chart_series(bundle)

    filled_by_segment = {}
    for row in bundle.trades:
        if row["portfolio"] != "strategy" or row["status"] != "filled":
            continue
        filled_by_segment.setdefault(row["segment"], 0)
        filled_by_segment[row["segment"]] += 1

    for segment, count in filled_by_segment.items():
        markers = len(series[segment].buy_trades) + len(series[segment].sell_trades)
        assert markers == count
        for trade in series[segment].buy_trades + series[segment].sell_trades:
            assert 0 <= trade["index"] < len(series[segment].timestamps)
            assert series[segment].timestamps[trade["index"]] == trade["ts"]
