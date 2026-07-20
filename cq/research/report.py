"""Run reports.

A number without its provenance is not reproducible, and this project has
already lost work to exactly that: tables whose figures could not be matched
to a code version, and results that turned out to have been produced by an
engine with a since-fixed defect.

Every report therefore carries the git commit, the data fingerprint, the cost
and funding assumptions, and the split fingerprint. If a figure cannot be
reproduced, the report says enough to find out why.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cq.context import Series
from cq.engine.loop import RunResult
from cq.research.metrics import Metrics, compute_metrics, trades_from_fills
from cq.research.split import SplitPlan
from cq.research.stats import BootstrapResult, bootstrap_trades

DEFAULT_REPORT_DIR = Path("reports")


def git_commit() -> str:
    """The commit that produced a result, or a marker that it is unknown."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git from PATH is intended
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = out.stdout.strip()
    if not commit:
        return "unknown"
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],  # noqa: S607 - git from PATH is intended
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    # An uncommitted tree cannot be checked out again, so say so.
    return f"{commit}-dirty" if dirty else commit


def series_fingerprint(series: Series) -> str:
    """Hash of the actual bars a run consumed.

    Catches the case where a result cannot be reproduced because the data
    underneath it changed — a re-sync filled a gap, or the range moved.
    """
    digest = hashlib.sha256()
    digest.update(series.inst_id.encode())
    digest.update(series.timeframe.encode())
    for column in (series.ts, series.open, series.high, series.low, series.close, series.volume):
        digest.update(np.ascontiguousarray(column).tobytes())
    return digest.hexdigest()[:16]


@dataclass
class Report:
    """One run, its metrics, and everything needed to reproduce it."""

    result: RunResult
    metrics: Metrics
    bootstrap: BootstrapResult
    data_fingerprint: str
    commit: str
    generated_at: str
    split: SplitPlan | None = None
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"# {self.result.strategy} — {self.result.inst_id} {self.result.timeframe}",
            "",
            "## Result",
            self.result.summary(),
            "",
            "## Metrics",
            self.metrics.summary(),
            "",
            "## Robustness",
            self.bootstrap.summary(),
            "",
            "## Provenance",
            f"  commit           {self.commit}",
            f"  data             {self.data_fingerprint}",
            f"  generated        {self.generated_at}",
            f"  costs            {self.result.cost_label}",
            f"  funding          {self.result.funding_label}",
        ]
        if self.split is not None:
            lines.append(f"  split            {self.split.study} ({self.split.fingerprint})")

        warnings = list(self.notes)
        if self.split is not None:
            warnings.extend(self.split.warnings())
        if self.result.rejections:
            warnings.append(
                f"{len(self.result.rejections)} orders could not be filled "
                f"(zero-volume bars, lot size or minimum notional)"
            )
        if warnings:
            lines += ["", "## What this cannot claim"]
            lines += [f"  - {note}" for note in warnings]

        return "\n".join(lines) + "\n"

    def write(self, directory: Path | str = DEFAULT_REPORT_DIR) -> Path:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = self.generated_at.replace(":", "").replace("-", "")[:15]
        path = target / f"{self.result.strategy}_{self.result.inst_id}_{stamp}.md"
        path.write_text(self.render(), encoding="utf-8")
        return path


def build_report(
    result: RunResult,
    series: Series,
    split: SplitPlan | None = None,
    bootstrap_samples: int = 10_000,
    seed: int = 0,
    notes: list[str] | None = None,
) -> Report:
    """Assemble metrics, robustness and provenance for one run."""
    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    trade_returns = [t.return_pct for t in trades_from_fills(result.fills)]
    return Report(
        result=result,
        metrics=metrics,
        bootstrap=bootstrap_trades(trade_returns, samples=bootstrap_samples, seed=seed),
        data_fingerprint=series_fingerprint(series),
        commit=git_commit(),
        generated_at=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        split=split,
        notes=notes or [],
    )
