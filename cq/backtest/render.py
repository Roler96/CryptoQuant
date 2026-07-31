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
