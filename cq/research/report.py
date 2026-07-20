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
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cq.context import Series
from cq.engine.loop import RunResult
from cq.research.metrics import Metrics, compute_metrics, episode_returns
from cq.research.split import SplitPlan, from_ms
from cq.research.stats import BootstrapResult, bootstrap_trades

DEFAULT_REPORT_DIR = Path("reports")


class ProvenanceError(Exception):
    """A report was asked to describe a run with data that is not its own."""


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
    aux_fingerprints: dict[tuple[str, str], str] = field(default_factory=dict)
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
            "  resampled over the portfolio's return across each position held,",
            "  including any position still open at the end of the run",
            self.bootstrap.summary(),
            "",
            "## Provenance",
            f"  commit           {self.commit}",
            f"  data             {self.data_fingerprint}",
            f"  generated        {self.generated_at}",
            f"  costs            {self.result.cost_label}",
            f"  funding          {self.result.funding_label}",
            f"  funding data     {self.result.funding_fingerprint}",
        ]
        for (inst_id, timeframe), fingerprint in sorted(self.aux_fingerprints.items()):
            lines.append(f"  aux {inst_id} {timeframe}  {fingerprint}")
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
    aux: Iterable[Series] = (),
) -> Report:
    """Assemble metrics, robustness and provenance for one run.

    The series and the split are checked against the run rather than taken on
    trust. A provenance block that can be attached to any run is decoration:
    it was possible here to label a 2021 backtest with a 2026 forward-holdout
    plan and have the report state, in its own words, that the result was
    out-of-sample.
    """
    _require_matching_series(result, series)
    aux = list(aux)
    _require_declared_aux(result, aux)

    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    portfolio_returns = episode_returns(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    return Report(
        result=result,
        metrics=metrics,
        bootstrap=bootstrap_trades(portfolio_returns, samples=bootstrap_samples, seed=seed),
        data_fingerprint=series_fingerprint(series),
        aux_fingerprints={s.key: series_fingerprint(s) for s in aux},
        commit=git_commit(),
        generated_at=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        split=split,
        notes=(notes or []) + _split_mismatches(result, split),
    )


def _require_matching_series(result: RunResult, series: Series) -> None:
    """Fail unless `series` is the data the run actually consumed."""
    if (series.inst_id, series.timeframe) != (result.inst_id, result.timeframe):
        raise ProvenanceError(
            f"report was given {series.inst_id} {series.timeframe} but the run is "
            f"{result.inst_id} {result.timeframe}; the fingerprint would describe "
            f"data the result did not come from"
        )
    if len(series) != result.bars or (
        result.timestamps and int(series.ts[0]) != result.timestamps[0]
    ):
        raise ProvenanceError(
            f"report was given {len(series)} bars starting at "
            f"{int(series.ts[0]) if len(series) else '-'} but the run covered "
            f"{result.bars} bars starting at "
            f"{result.timestamps[0] if result.timestamps else '-'}"
        )


def _require_declared_aux(result: RunResult, aux: list[Series]) -> None:
    """Fail unless the auxiliary series match the ones the run was given."""
    given = tuple(sorted(s.key for s in aux))
    ran_with = tuple(sorted(result.aux_keys))
    if given != ran_with:
        raise ProvenanceError(
            f"run consumed auxiliary markets {list(ran_with)} but the report was "
            f"given {list(given)}; a run that read a second series cannot be "
            f"reproduced from the primary alone"
        )


def _split_mismatches(result: RunResult, split: SplitPlan | None) -> list[str]:
    """Warnings for a split whose dates do not describe this run."""
    if split is None or not result.timestamps:
        return []
    first, last = result.timestamps[0], result.timestamps[-1]
    covered = [s for s in split.segments if s.start_ms <= first and last < s.end_ms]
    if covered:
        return []
    spans = ", ".join(f"{s.name} {s.start}..{s.end}" for s in split.segments)
    return [
        f"the run covers {from_ms(first)}..{from_ms(last)}, which no segment of "
        f"split '{split.study}' contains ({spans}); this report is labelled with a "
        f"plan it was not produced under, and the split's claims do not apply to it"
    ]
