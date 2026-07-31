"""Comparison metrics and durable artifacts for split backtests."""

from __future__ import annotations

import csv
import datetime as dt
import io
import itertools
import json
import math
import os
import re
import statistics
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from cq.context import Series, series_fingerprint
from cq.core.clock import duration_ms
from cq.engine.loop import AccountEventRecord, RunResult, TransactionRecord

YEAR_MS = 365 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class SegmentResult:
    """One independently funded evaluation segment and its causal pre-roll."""

    name: str
    result: RunResult
    evaluation_series: Series
    warmup_bars: int


@dataclass(frozen=True)
class PerformanceMetrics:
    bars: int
    warmup_bars: int
    fills: int
    rejected: int
    initial_equity: float
    final_equity: float
    total_return: float
    annualized_return: float | None
    max_drawdown: float
    annualized_volatility: float | None
    sharpe_ratio: float | None


def performance(segment: SegmentResult) -> PerformanceMetrics:
    """Compute comparable metrics from the evaluation-only equity curve."""
    result = segment.result
    values = [result.initial_cash, *result.equity]
    peak = result.initial_cash
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)

    annualized_return: float | None = None
    if result.bars >= 2 and result.final_equity > 0:
        elapsed_ms = (
            result.timestamps[-1]
            + duration_ms(result.timeframe)
            - result.timestamps[0]
        )
        if elapsed_ms > 0:
            annualized_return = (
                result.final_equity / result.initial_cash
            ) ** (YEAR_MS / elapsed_ms) - 1.0

    returns = [
        current / previous - 1.0
        for previous, current in itertools.pairwise(values)
        if previous > 0
    ]
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    if len(returns) >= 2:
        deviation = statistics.stdev(returns)
        periods_per_year = YEAR_MS / duration_ms(result.timeframe)
        annualized_volatility = deviation * math.sqrt(periods_per_year)
        if deviation > 0:
            sharpe_ratio = statistics.fmean(returns) / deviation * math.sqrt(
                periods_per_year
            )

    return PerformanceMetrics(
        bars=result.bars,
        warmup_bars=segment.warmup_bars,
        fills=len(result.fills),
        rejected=len(result.rejections),
        initial_equity=result.initial_cash,
        final_equity=result.final_equity,
        total_return=result.total_return,
        annualized_return=annualized_return,
        max_drawdown=max_drawdown,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=sharpe_ratio,
    )


def build_payload(
    *,
    run_id: str,
    created_at: str,
    artifact_dir: Path,
    config: dict[str, Any],
    full_series: Series,
    split: float,
    cut_index: int,
    historical: SegmentResult,
    recent: SegmentResult,
    historical_benchmark: SegmentResult,
    recent_benchmark: SegmentResult,
    full: SegmentResult,
    full_benchmark: SegmentResult,
) -> dict[str, Any]:
    """Build the JSON authority shared by stdout and ``summary.json``."""
    segments = (
        (historical, historical_benchmark),
        (recent, recent_benchmark),
        (full, full_benchmark),
    )
    payload: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": created_at,
        "artifact_dir": str(artifact_dir),
        "config": config,
        "metric_definitions": {
            "annualization_days": 365,
            "risk_free_rate": 0.0,
            "returns": "bar-to-bar changes in evaluation equity",
            "annualized_return": "compound return over evaluation wall-clock duration",
            "max_drawdown": "minimum evaluation equity / prior peak - 1",
        },
        "split": {
            "ratio": split,
            "total_bars": len(full_series),
            "cut_index": cut_index,
            "boundary_ms": int(full_series.ts[cut_index]),
            "boundary_time": utc_iso(int(full_series.ts[cut_index])),
            "full_data_fingerprint": series_fingerprint(full_series),
        },
        "segments": {},
        "transactions": [],
        "account_events": [],
    }
    segment_payloads: dict[str, Any] = {}
    transactions: list[dict[str, Any]] = []
    account_events: list[dict[str, Any]] = []
    for segment, benchmark in segments:
        result = segment.result
        metric = performance(segment)
        benchmark_metric = performance(benchmark)
        segment_payloads[segment.name] = {
            "evaluation_start_ms": (
                int(segment.evaluation_series.ts[0])
                if len(segment.evaluation_series)
                else None
            ),
            "evaluation_start": (
                utc_iso(int(segment.evaluation_series.ts[0]))
                if len(segment.evaluation_series)
                else None
            ),
            "evaluation_end_ms": (
                int(segment.evaluation_series.ts[-1]) + duration_ms(result.timeframe)
                if len(segment.evaluation_series)
                else None
            ),
            "evaluation_end": (
                utc_iso(
                    int(segment.evaluation_series.ts[-1])
                    + duration_ms(result.timeframe)
                )
                if len(segment.evaluation_series)
                else None
            ),
            "warmup_bars": segment.warmup_bars,
            "evaluation_data_fingerprint": series_fingerprint(
                segment.evaluation_series
            ),
            "manifest": asdict(result.manifest),
            "metrics": asdict(metric),
            "benchmark": {
                "name": benchmark.result.strategy,
                "manifest": asdict(benchmark.result.manifest),
                "metrics": asdict(benchmark_metric),
            },
            "excess": {
                "total_return": metric.total_return - benchmark_metric.total_return,
                "annualized_return": _difference(
                    metric.annualized_return,
                    benchmark_metric.annualized_return,
                ),
                "max_drawdown": metric.max_drawdown - benchmark_metric.max_drawdown,
                "sharpe_ratio": _difference(
                    metric.sharpe_ratio,
                    benchmark_metric.sharpe_ratio,
                ),
            },
        }
        for portfolio, run in (("strategy", result), ("benchmark", benchmark.result)):
            for sequence, record in enumerate(run.transactions, start=1):
                row = {
                    "segment": segment.name,
                    "portfolio": portfolio,
                    "sequence": sequence,
                    **asdict(record),
                }
                row["signal_time_iso"] = (
                    utc_iso(record.signal_time)
                    if record.signal_time is not None
                    else None
                )
                row["execution_time_iso"] = utc_iso(record.execution_time)
                transactions.append(row)
            for sequence, event in enumerate(run.account_events, start=1):
                row = {
                    "segment": segment.name,
                    "portfolio": portfolio,
                    "sequence": sequence,
                    **asdict(event),
                }
                row["time_iso"] = utc_iso(event.ts)
                account_events.append(row)
    transactions.sort(
        key=lambda row: (
            row["execution_time"],
            row["segment"],
            row["portfolio"],
            row["sequence"],
        )
    )
    account_events.sort(
        key=lambda row: (
            row["ts"],
            row["segment"],
            row["portfolio"],
            row["sequence"],
        )
    )
    payload["segments"] = segment_payloads
    payload["transactions"] = transactions
    payload["account_events"] = account_events
    return payload


def render_text(payload: dict[str, Any], show_trades: int = 0) -> str:
    """Render a stable, dependency-free terminal comparison."""
    config = payload["config"]
    split = payload["split"]
    historical = payload["segments"]["historical"]["metrics"]
    recent = payload["segments"]["recent"]["metrics"]
    historical_benchmark = payload["segments"]["historical"]["benchmark"]["metrics"]
    recent_benchmark = payload["segments"]["recent"]["benchmark"]["metrics"]
    full = payload["segments"]["full"]["metrics"]
    full_benchmark = payload["segments"]["full"]["benchmark"]["metrics"]
    lines = [
        f"Backtest: {config['strategy']}",
        (
            f"Instrument: {config['inst_id']} ({config['market_type']})"
            f" | Timeframe: {config['timeframe']}"
        ),
        (
            f"Data: {config['data_start']} -> {config['data_end']}"
            f" | Split: {split['ratio']:.4f}"
        ),
        (
            f"Boundary: {split['boundary_time']}"
            f" | {split['cut_index']} historical / "
            f"{split['total_bars'] - split['cut_index']} recent bars"
        ),
        (
            f"Sizing: {config['sizing']} | Initial cash: "
            f"{config['initial_cash']:,.2f}"
        ),
        f"Costs: {config['costs']}",
        f"Funding: {config['funding']}",
        "",
        (
            f"{'Metric':<24}{'Hist strategy':>16}{'Hist B&H':>16}"
            f"{'Recent strategy':>16}{'Recent B&H':>16}"
        ),
        "-" * 88,
    ]
    rows = (
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
    for label, key, formatter in rows:
        lines.append(
            f"{label:<24}{formatter(historical[key]):>16}"
            f"{formatter(historical_benchmark[key]):>16}"
            f"{formatter(recent[key]):>16}"
            f"{formatter(recent_benchmark[key]):>16}"
        )

    lines.extend(
        [
            "",
            "Full period (unsplit)",
            f"{'Metric':<24}{'Strategy':>16}{'Buy & hold':>16}",
            "-" * 56,
        ]
    )
    for label, key, formatter in rows:
        lines.append(
            f"{label:<24}{formatter(full[key]):>16}"
            f"{formatter(full_benchmark[key]):>16}"
        )

    annualized_delta = _points_delta(
        recent["annualized_return"], historical["annualized_return"]
    )
    drawdown_delta = _points_delta(
        recent["max_drawdown"], historical["max_drawdown"]
    )
    sharpe_delta = _plain_delta(
        recent["sharpe_ratio"], historical["sharpe_ratio"]
    )
    historical_excess = _points_delta(
        historical["total_return"], historical_benchmark["total_return"]
    )
    recent_excess = _points_delta(
        recent["total_return"], recent_benchmark["total_return"]
    )
    historical_annualized_excess = _points_delta(
        historical["annualized_return"],
        historical_benchmark["annualized_return"],
    )
    recent_annualized_excess = _points_delta(
        recent["annualized_return"],
        recent_benchmark["annualized_return"],
    )
    full_excess = _points_delta(
        full["total_return"], full_benchmark["total_return"]
    )
    full_annualized_excess = _points_delta(
        full["annualized_return"], full_benchmark["annualized_return"]
    )
    lines.extend(
        [
            "",
            "Strategy vs buy-and-hold",
            f"  historical total return:      {historical_excess}",
            f"  historical annualized return: {historical_annualized_excess}",
            f"  recent total return:          {recent_excess}",
            f"  recent annualized return:     {recent_annualized_excess}",
            f"  full total return:            {full_excess}",
            f"  full annualized return:       {full_annualized_excess}",
            "",
            "Recent vs historical",
            f"  annualized return: {annualized_delta}",
            f"  max drawdown:      {drawdown_delta}",
            f"  Sharpe ratio:      {sharpe_delta}",
            "",
            "Transactions",
            (
                f"  historical strategy:  {historical['fills']} filled, "
                f"{historical['rejected']} rejected"
            ),
            (
                f"  historical benchmark: {historical_benchmark['fills']} filled, "
                f"{historical_benchmark['rejected']} rejected"
            ),
            (
                f"  recent strategy:      {recent['fills']} filled, "
                f"{recent['rejected']} rejected"
            ),
            (
                f"  recent benchmark:     {recent_benchmark['fills']} filled, "
                f"{recent_benchmark['rejected']} rejected"
            ),
            (
                f"  full strategy:        {full['fills']} filled, "
                f"{full['rejected']} rejected"
            ),
            (
                f"  full benchmark:       {full_benchmark['fills']} filled, "
                f"{full_benchmark['rejected']} rejected"
            ),
            f"  details: {payload['artifact_dir']}",
        ]
    )
    if show_trades > 0:
        selected = payload["transactions"][-show_trades:]
        lines.extend(["", f"Last {len(selected)} transaction(s)"])
        for row in selected:
            quantity = row["filled_quantity"] or row["rounded_quantity"]
            lines.append(
                f"  {row['execution_time_iso']} {row['segment']:<10} "
                f"{row['portfolio']:<9} "
                f"{row['status']:<8} {row['side']:<4} {quantity:.8g} "
                f"@ {_price(row['execution_price'])} fee {row['fee']:.6g} "
                f"{row['reason']}"
            )
    return "\n".join(lines)


def write_bundle(payload: dict[str, Any], artifact_dir: Path) -> None:
    """Atomically persist the summary and flat event ledgers."""
    artifact_dir.mkdir(parents=True, exist_ok=False)
    _atomic_write(
        artifact_dir / "summary.json",
        json.dumps(summary_payload(payload), ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
    )
    _atomic_write(
        artifact_dir / "trades.csv",
        _csv_text(
            payload["transactions"],
            [
                "segment",
                "portfolio",
                "sequence",
                *(field.name for field in fields(TransactionRecord)),
                "signal_time_iso",
                "execution_time_iso",
            ],
        ),
    )
    _atomic_write(
        artifact_dir / "account_events.csv",
        _csv_text(
            payload["account_events"],
            [
                "segment",
                "portfolio",
                "sequence",
                *(field.name for field in fields(AccountEventRecord)),
                "time_iso",
            ],
        ),
    )


def summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The compact machine report; detailed events stay in their CSV ledgers."""
    summary = {
        key: value
        for key, value in payload.items()
        if key not in ("transactions", "account_events")
    }
    summary["ledgers"] = {
        "transactions": {
            "file": "trades.csv",
            "rows": len(payload["transactions"]),
        },
        "account_events": {
            "file": "account_events.csv",
            "rows": len(payload["account_events"]),
        },
    }
    return summary


def new_run_identity(strategy: str, inst_id: str, output_dir: Path) -> tuple[str, str, Path]:
    now = dt.datetime.now(dt.UTC)
    created_at = now.isoformat()
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    raw_slug = "-".join(part.lower() for part in (strategy, inst_id) if part)
    slug = re.sub(r"[^a-z0-9]+", "-", raw_slug).strip("-") or "backtest"
    run_id = f"{timestamp}-{slug}"
    return run_id, created_at, output_dir / run_id


def utc_iso(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000, dt.UTC).isoformat()


def _csv_text(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _integer(value: int | float | None) -> str:
    return "-" if value is None else f"{int(value):,}"


def _money(value: int | float | None) -> str:
    return "-" if value is None else f"{float(value):,.2f}"


def _percent(value: int | float | None) -> str:
    return "-" if value is None else f"{float(value) * 100:+.2f}%"


def _number(value: int | float | None) -> str:
    return "-" if value is None else f"{float(value):.2f}"


def _price(value: int | float | None) -> str:
    return "-" if value is None else f"{float(value):.10g}"


def _points_delta(current: float | None, baseline: float | None) -> str:
    if current is None or baseline is None:
        return "-"
    return f"{(current - baseline) * 100:+.2f} pp"


def _plain_delta(current: float | None, baseline: float | None) -> str:
    if current is None or baseline is None:
        return "-"
    return f"{current - baseline:+.2f}"


def _difference(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return current - baseline
