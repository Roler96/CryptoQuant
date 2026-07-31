"""Render a self-contained HTML report from a persisted backtest run bundle."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
