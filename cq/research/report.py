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
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from cq.context import Series, series_fingerprint
from cq.engine.loop import RunResult
from cq.research.metrics import Metrics, compute_metrics, episode_returns
from cq.research.split import SplitPlan, from_ms
from cq.research.stats import BootstrapResult, bootstrap_trades

# series_fingerprint moved to cq.context so the engine can pin it into the run
# manifest as it runs. Re-exported here because callers and tests reach for it
# under this module, where the reporting story still lives.
__all__ = ["ProvenanceError", "Report", "build_report", "git_commit", "series_fingerprint"]

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
    series: Series | None = None,
    split: SplitPlan | None = None,
    bootstrap_samples: int = 10_000,
    seed: int = 0,
    notes: list[str] | None = None,
    aux: Iterable[Series] = (),
) -> Report:
    """Assemble metrics, robustness and provenance for one run.

    The run's own manifest is the authority on what data and configuration it
    consumed; the report reads its fingerprints from there rather than deciding
    for itself. A `series` (and `aux`) may still be passed, and then it is
    *verified* against the manifest — instrument, timeframe, shape and, crucially,
    full content — and rejected on any disagreement. Recomputing the fingerprint
    from a passed-in series and trusting it, the earlier design, meant a run on
    data A could be handed a doctored data B agreeing on instrument, timeframe,
    length and first timestamp, and the report would state in its own words that
    the figures came from B. Passing nothing reports straight from the manifest.

    The split is checked against the run the same way: a provenance block that
    can be attached to any run is decoration, and it was possible here to label
    a 2021 backtest with a 2026 forward-holdout plan and have the report claim
    the result was out-of-sample.
    """
    aux = list(aux)
    if series is not None:
        _require_matching_series(result, series)
        _require_declared_aux(result, aux)
        _require_matching_aux_content(result, aux)

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
        data_fingerprint=result.manifest.primary_fingerprint,
        aux_fingerprints={
            (inst_id, timeframe): fingerprint
            for inst_id, timeframe, fingerprint in result.manifest.aux_fingerprints
        },
        commit=git_commit(),
        generated_at=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        split=split,
        notes=(notes or []) + _split_mismatches(result, split),
    )


def _require_matching_series(result: RunResult, series: Series) -> None:
    """Fail unless `series` is, to the byte, the data the run consumed."""
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
    # The check the structural one above cannot make: same instrument, timeframe,
    # length and first timestamp, but an edited price somewhere inside. Only the
    # content fingerprint, pinned when the run happened, catches that.
    if series_fingerprint(series) != result.manifest.primary_fingerprint:
        raise ProvenanceError(
            f"report was given {series.inst_id} {series.timeframe} matching the run's "
            f"shape, but its content fingerprint {series_fingerprint(series)} is not the "
            f"{result.manifest.primary_fingerprint} the run consumed; the bars were "
            f"changed after the run, and the result did not come from them"
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


def _require_matching_aux_content(result: RunResult, aux: list[Series]) -> None:
    """Fail unless each auxiliary series is, to the byte, what the run read."""
    pinned = {
        (inst_id, timeframe): fp
        for inst_id, timeframe, fp in result.manifest.aux_fingerprints
    }
    for s in aux:
        expected = pinned.get(s.key)
        actual = series_fingerprint(s)
        if expected is not None and actual != expected:
            raise ProvenanceError(
                f"auxiliary market {s.inst_id} {s.timeframe} fingerprints {actual} but the "
                f"run read {expected}; the report would describe data the result did not "
                f"come from"
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
