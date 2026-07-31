"""Offline backtest CLI registry, execution, and expected failures."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence

from cq.backtest.registry import REGISTRY
from cq.cli import build_parser, main
from cq.core.clock import HOUR_MS
from cq.data.store import Store
from cq.strategy.donchian import DonchianTrend

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


def test_donchian_registry_builds_strategy_from_parsed_lookback():
    args = build_parser().parse_args(
        ["backtest", "donchian", "--inst", "DOGE-USDT", "--lookback", "7"]
    )

    strategy = REGISTRY["donchian"].build(args)

    assert isinstance(strategy, DonchianTrend)
    assert strategy.name == "donchian-trend-7"


def test_backtest_command_runs_stored_series_through_real_engine(tmp_path, capsys):
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
            "--initial-cash",
            "1000",
            "--fee-bps",
            "0",
            "--slippage-bps",
            "0",
            "--output-dir",
            str(output_dir),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Backtest: donchian-trend-3" in output
    assert "Instrument: DOGE-USDT (spot) | Timeframe: 1h" in output
    assert "11 historical / 5 recent bars" in output
    assert "Full period (unsplit)" in output
    artifact_dir = next(output_dir.iterdir())
    assert (artifact_dir / "summary.json").exists()
    assert (artifact_dir / "trades.csv").exists()
    assert (artifact_dir / "account_events.csv").exists()
    summary = json.loads((artifact_dir / "summary.json").read_text())
    assert "transactions" not in summary
    assert summary["ledgers"]["transactions"]["file"] == "trades.csv"
    assert summary["segments"]["historical"]["benchmark"]["name"] == "buy-and-hold"
    assert (
        summary["segments"]["historical"]["benchmark"]["metrics"]["fills"] == 1
    )
    assert summary["segments"]["full"]["metrics"]["bars"] == len(closes)
    assert summary["segments"]["full"]["benchmark"]["metrics"]["fills"] == 1
    assert (artifact_dir / "account_events.csv").read_text().startswith(
        "segment,portfolio,sequence,"
    )


def test_split_ratio_is_configurable():
    args = build_parser().parse_args(
        ["backtest", "donchian", "--inst", "DOGE-USDT", "--split", "0.8"]
    )

    assert args.split == 0.8


def test_invalid_split_is_an_expected_failure(tmp_path, capsys):
    exit_code = main(
        [
            "backtest",
            "donchian",
            "--db",
            str(tmp_path / "cq.db"),
            "--inst",
            "DOGE-USDT",
            "--split",
            "1",
        ]
    )

    assert exit_code == 1
    assert "--split must be greater than 0 and less than 1" in capsys.readouterr().out


def test_json_report_and_trade_ledger_are_written(tmp_path, capsys):
    db = tmp_path / "cq.db"
    output_dir = tmp_path / "reports"
    closes = [10, 10, 10, 11, 12, 5, 5, 5, 10, 11, 4, 4]
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
            "2",
            "--split",
            "0.5",
            "--format",
            "json",
            "--output-dir",
            str(output_dir),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["split"]["cut_index"] == 6
    assert payload["segments"]["historical"]["metrics"]["bars"] == 6
    assert payload["segments"]["recent"]["metrics"]["bars"] == 6
    assert payload["segments"]["full"]["metrics"]["bars"] == 12
    assert payload["ledgers"]["transactions"]["rows"] > 0

    artifact_dir = next(output_dir.iterdir())
    stored = json.loads((artifact_dir / "summary.json").read_text())
    assert stored["run_id"] == payload["run_id"]
    with (artifact_dir / "trades.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {
        "portfolio",
        "signal_time_iso",
        "execution_time_iso",
        "cash_before",
        "cash_after",
    } <= set(rows[0])
    assert {row["portfolio"] for row in rows} == {"strategy", "benchmark"}
    assert {row["segment"] for row in rows} == {"historical", "recent", "full"}
    execution_times = [int(row["execution_time"]) for row in rows]
    assert execution_times == sorted(execution_times)


def test_equity_curve_is_persisted_per_segment_and_portfolio(tmp_path, capsys):
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

    artifact_dir = next(output_dir.iterdir())
    summary = json.loads((artifact_dir / "summary.json").read_text())
    assert "equity" not in summary
    assert summary["ledgers"]["equity"]["file"] == "equity.csv"

    with (artifact_dir / "equity.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert {"segment", "portfolio", "sequence", "ts", "ts_iso", "equity"} <= set(rows[0])
    assert {row["segment"] for row in rows} == {"historical", "recent", "full"}
    assert {row["portfolio"] for row in rows} == {"strategy", "benchmark"}

    expected_rows = sum(
        summary["segments"][segment]["metrics"]["bars"]
        + summary["segments"][segment]["benchmark"]["metrics"]["bars"]
        for segment in ("historical", "recent", "full")
    )
    assert len(rows) == expected_rows
    assert summary["ledgers"]["equity"]["rows"] == expected_rows

    historical_strategy_rows = [
        row
        for row in rows
        if row["segment"] == "historical" and row["portfolio"] == "strategy"
    ]
    assert len(historical_strategy_rows) == summary["segments"]["historical"]["metrics"]["bars"]
    sequences = sorted(int(row["sequence"]) for row in historical_strategy_rows)
    assert sequences == list(range(1, len(historical_strategy_rows) + 1))


def test_spot_rejects_swap_only_arguments(tmp_path, capsys):
    exit_code = main(
        [
            "backtest",
            "donchian",
            "--db",
            str(tmp_path / "cq.db"),
            "--inst",
            "DOGE-USDT",
            "--leverage",
            "2",
        ]
    )

    assert exit_code == 1
    assert "only apply to swap instruments" in capsys.readouterr().out


def test_actual_swap_funding_failure_is_reported_without_traceback(tmp_path, capsys):
    db = tmp_path / "cq.db"
    _store_closes(db, "DOGE-USDT-SWAP", [10, 11])

    exit_code = main(
        [
            "backtest",
            "donchian",
            "--db",
            str(db),
            "--inst",
            "DOGE-USDT-SWAP",
            "--lookback",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "no archived funding rate" in output
    assert "the archive is empty" in output
    assert "Traceback" not in output


def test_assumed_funding_requires_a_rate(tmp_path, capsys):
    exit_code = main(
        [
            "backtest",
            "donchian",
            "--db",
            str(tmp_path / "cq.db"),
            "--inst",
            "DOGE-USDT-SWAP",
            "--funding",
            "assumed",
        ]
    )

    assert exit_code == 1
    assert "--funding-rate is required" in capsys.readouterr().out
