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


from cq.backtest.render import _render_header, _render_metrics_table


def test_render_header_includes_strategy_and_instrument(tmp_path, capsys):
    bundle = load_bundle(_build_run_dir(tmp_path, capsys))

    header = _render_header(bundle)

    assert "donchian-trend-3" in header
    assert "DOGE-USDT" in header
    assert bundle.summary["run_id"] in header


def test_render_metrics_table_has_six_data_columns_per_row(tmp_path, capsys):
    bundle = load_bundle(_build_run_dir(tmp_path, capsys))

    table = _render_metrics_table(bundle)

    assert table.count("<tr>") == 1 + len(
        # header row + one row per metric
        [None for _ in range(11)]
    )
    assert "Sharpe ratio" in table
    assert "Historical strategy" in table
    assert "B&amp;H" in table


import re
import shutil
import subprocess

from cq.backtest.render import render_html, write_report


def test_render_html_embeds_escaped_json_data_block(tmp_path, capsys):
    bundle = load_bundle(_build_run_dir(tmp_path, capsys))
    series = build_chart_series(bundle)

    html = render_html(bundle, series)

    assert "<title>" in html
    assert bundle.summary["run_id"] in html
    assert "uPlot" in html
    assert "MIT License" in html
    match = re.search(
        r'<script id="report-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    data = json.loads(match.group(1))
    assert set(data["segments"]) == set(SEGMENT_NAMES)
    historical = data["segments"]["historical"]
    assert len(historical["timestamps"]) == len(series["historical"].timestamps)


def test_render_html_glue_script_is_syntactically_valid_javascript(tmp_path, capsys):
    bundle = load_bundle(_build_run_dir(tmp_path, capsys))
    series = build_chart_series(bundle)

    html = render_html(bundle, series)

    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    glue_scripts = [s for s in scripts if "uPlot(" in s and "var uPlot" not in s]
    assert glue_scripts
    # `node --check /dev/stdin` fails on some Linux setups (this box included):
    # readFileSync resolves the piped fd's realpath to a bogus "pipe:[N]"
    # string and then tries to open *that* -- ENOENT, unrelated to JS syntax.
    # Writing the extracted glue script to a real file sidesteps that and
    # checks the exact same thing: does node accept this script's syntax.
    node = shutil.which("node")
    assert node is not None, "node must be on PATH to check the glue script"
    script_path = tmp_path / "glue.js"
    script_path.write_text(glue_scripts[0], encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - `node` is resolved via shutil.which above
        [node, "--check", str(script_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_write_report_writes_and_overwrites_report_html(tmp_path, capsys):
    run_dir = _build_run_dir(tmp_path, capsys)

    first_path = write_report(run_dir)
    assert first_path == run_dir / "report.html"
    assert first_path.exists()
    first_size = first_path.stat().st_size

    second_path = write_report(run_dir)
    assert second_path == first_path
    assert second_path.stat().st_size == first_size
