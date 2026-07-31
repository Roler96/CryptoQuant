"""Render a self-contained HTML report from a persisted backtest run bundle."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from html import escape as _escape
from pathlib import Path
from typing import Any

from cq.backtest.report import _integer, _money, _number, _percent

_REQUIRED_FILES = ("summary.json", "trades.csv", "account_events.csv", "equity.csv")


class RunBundleError(Exception):
    """A run directory is missing a file `render()` needs, or its files disagree."""


@dataclass(frozen=True)
class RunBundle:
    """The four files `write_bundle` persists, loaded back for offline rendering."""

    run_dir: Path
    summary: dict[str, Any]
    trades: list[dict[str, str]]
    account_events: list[dict[str, str]]
    equity: list[dict[str, str]]


SEGMENT_NAMES = ("historical", "recent", "full")

_METRIC_ROWS = (
    ("Evaluation bars", "bars", _integer),
    ("Warmup bars", "warmup_bars", _integer),
    ("Fills", "fills", _integer),
    ("Rejected", "rejected", _integer),
    ("Initial equity", "initial_equity", _money),
    ("Final equity", "final_equity", _money),
    ("Total return", "total_return", _percent),
    ("Annualized return", "annualized_return", _percent),
    ("Max drawdown", "max_drawdown", _percent),
    ("Annualized volatility", "annualized_volatility", _percent),
    ("Sharpe ratio", "sharpe_ratio", _number),
)

_METRIC_COLUMNS = (
    ("historical", False, "Historical strategy"),
    ("historical", True, "Historical B&H"),
    ("recent", False, "Recent strategy"),
    ("recent", True, "Recent B&H"),
    ("full", False, "Full strategy"),
    ("full", True, "Full B&H"),
)


@dataclass(frozen=True)
class SegmentSeries:
    """One segment's chart-ready arrays: equal-length, index-aligned to `timestamps`."""

    timestamps: list[int]
    strategy_equity: list[float]
    benchmark_equity: list[float]
    strategy_drawdown: list[float]
    benchmark_drawdown: list[float]
    buy_trades: list[dict[str, Any]]
    sell_trades: list[dict[str, Any]]
    account_events: list[dict[str, Any]]


def load_bundle(run_dir: Path) -> RunBundle:
    """Read a run directory's four files; refuse a partial or pre-equity.csv bundle."""
    missing = [name for name in _REQUIRED_FILES if not (run_dir / name).exists()]
    if missing:
        hint = (
            " equity.csv is written by newer `cq backtest` runs -- re-run the "
            "backtest to regenerate this bundle."
            if "equity.csv" in missing
            else ""
        )
        raise RunBundleError(f"{run_dir} is missing {', '.join(missing)}.{hint}")
    summary = json.loads((run_dir / "summary.json").read_text())
    return RunBundle(
        run_dir=run_dir,
        summary=summary,
        trades=_read_csv(run_dir / "trades.csv"),
        account_events=_read_csv(run_dir / "account_events.csv"),
        equity=_read_csv(run_dir / "equity.csv"),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_chart_series(bundle: RunBundle) -> dict[str, SegmentSeries]:
    """Reshape the four ledger files into per-segment arrays a chart can plot."""
    series: dict[str, SegmentSeries] = {}
    for segment_name in SEGMENT_NAMES:
        strategy_points = _equity_points(bundle.equity, segment_name, "strategy")
        benchmark_points = _equity_points(bundle.equity, segment_name, "benchmark")
        if len(strategy_points) != len(benchmark_points) or any(
            left[0] != right[0] for left, right in zip(strategy_points, benchmark_points)
        ):
            raise RunBundleError(
                f"{bundle.run_dir}: strategy/benchmark equity timestamps diverge "
                f"for segment {segment_name!r}"
            )
        timestamps = [ts for ts, _ in strategy_points]
        strategy_equity = [value for _, value in strategy_points]
        benchmark_equity = [value for _, value in benchmark_points]
        segment_summary = bundle.summary["segments"][segment_name]
        strategy_drawdown = _drawdown(
            strategy_equity, segment_summary["metrics"]["initial_equity"]
        )
        benchmark_drawdown = _drawdown(
            benchmark_equity, segment_summary["benchmark"]["metrics"]["initial_equity"]
        )
        buy_trades, sell_trades = _segment_trades(bundle.trades, segment_name, timestamps)
        series[segment_name] = SegmentSeries(
            timestamps=timestamps,
            strategy_equity=strategy_equity,
            benchmark_equity=benchmark_equity,
            strategy_drawdown=strategy_drawdown,
            benchmark_drawdown=benchmark_drawdown,
            buy_trades=buy_trades,
            sell_trades=sell_trades,
            account_events=_segment_account_events(bundle.account_events, segment_name),
        )
    return series


def _equity_points(
    rows: list[dict[str, str]], segment: str, portfolio: str
) -> list[tuple[int, float]]:
    points = [
        (int(row["ts"]), float(row["equity"]))
        for row in rows
        if row["segment"] == segment and row["portfolio"] == portfolio
    ]
    points.sort(key=lambda point: point[0])
    return points


def _drawdown(equity: list[float], initial: float) -> list[float]:
    peak = initial
    curve: list[float] = []
    for value in equity:
        peak = max(peak, value)
        curve.append(value / peak - 1.0 if peak > 0 else 0.0)
    return curve


def _segment_trades(
    rows: list[dict[str, str]], segment: str, timestamps: list[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    index_by_ts = {ts: idx for idx, ts in enumerate(timestamps)}
    buys: list[dict[str, Any]] = []
    sells: list[dict[str, Any]] = []
    for row in rows:
        if row["segment"] != segment or row["portfolio"] != "strategy":
            continue
        if row["status"] != "filled":
            continue
        ts = int(row["execution_time"])
        # Transactions are recorded for every bar the strategy ran on, including
        # the recent segment's warmup bars; the evaluation curve starts later,
        # so a warmup-era trade has no matching index and is dropped here.
        index = index_by_ts.get(ts)
        if index is None:
            continue
        quantity = float(row["filled_quantity"]) or float(row["rounded_quantity"])
        marker = {
            "index": index,
            "ts": ts,
            "price": float(row["execution_price"]),
            "quantity": quantity,
            "fee": float(row["fee"]),
            "reason": row["reason"],
        }
        (buys if row["side"] == "buy" else sells).append(marker)
    return buys, sells


def _segment_account_events(
    rows: list[dict[str, str]], segment: str
) -> list[dict[str, Any]]:
    return [
        {
            "ts": int(row["ts"]),
            "event_type": row["event_type"],
            "amount": float(row["amount"]),
            "equity_after": float(row["equity_after"]),
        }
        for row in rows
        if row["segment"] == segment and row["portfolio"] == "strategy"
    ]


def _render_header(bundle: RunBundle) -> str:
    config = bundle.summary["config"]
    split = bundle.summary["split"]
    strategy = _escape(config['strategy'])
    inst_id = _escape(config['inst_id'])
    market_type = _escape(config['market_type'])
    timeframe = _escape(config['timeframe'])
    data_start = _escape(config['data_start'])
    data_end = _escape(config['data_end'])
    boundary_time = _escape(split['boundary_time'])
    run_id = _escape(bundle.summary['run_id'])
    costs = _escape(config['costs'])
    funding = _escape(config['funding'])
    return f"""<header>
<h1>{strategy}</h1>
<p>{inst_id} ({market_type}) | {timeframe}</p>
<p>{data_start} &rarr; {data_end} | split {split['ratio']:.4f} at {boundary_time}</p>
<p>run: {run_id} | costs: {costs} | funding: {funding}</p>
</header>
"""


def _metrics_for(segments: dict[str, Any], segment: str, benchmark: bool) -> dict[str, Any]:
    node = segments[segment]
    return node["benchmark"]["metrics"] if benchmark else node["metrics"]


def _render_metrics_table(bundle: RunBundle) -> str:
    segments = bundle.summary["segments"]
    labels = ("Metric", *(label for _, _, label in _METRIC_COLUMNS))
    header_cells = "".join(
        f"<th>{_escape(label)}</th>" for label in labels
    )
    body_rows = []
    for label, key, formatter in _METRIC_ROWS:
        cells = "".join(
            f"<td>{formatter(_metrics_for(segments, segment, benchmark)[key])}</td>"
            for segment, benchmark, _ in _METRIC_COLUMNS
        )
        body_rows.append(f"<tr><td>{_escape(label)}</td>{cells}</tr>")
    return f"""<table class="metrics">
<thead><tr>{header_cells}</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
"""
