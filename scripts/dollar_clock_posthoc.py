"""Post-hoc analysis behind RESULTS sections 3.2, 4.1 and 5.

Committed so those numbers are reproducible. Everything here ran *after* the
pre-registered diagnosis and changes no verdict; it exists because the first
draft of RESULTS quoted figures that lived only in a shell history, and because
a final review found three things the diagnosis computed but the report did not
print:

* the variance ratios, a pre-registered corroboration measure whose divergence
  the protocol committed in writing to report;
* the rank autocorrelation profile past lag 1, which by the report's own
  bid-ask-bounce argument carries the opposite implication to the one drawn;
* the coupling premise measured against the actual bucket duration rather than
  against inverse hourly turnover, which was only ever a proxy for it.

Run: .venv/bin/python scripts/dollar_clock_posthoc.py --db data/cq.db
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.coordinate_diagnostics import (
    combine_scales,
    delta_r_squared,
    paired_null_draws,
    rank_autocorrelation,
    rank_predictive_power,
    variance_ratio,
)
from cq.research.dollar_clock import (
    aggregate_by_edges,
    aggregate_calendar,
    bucket_edges,
    solve_bucket_size,
)
from cq.research.microstructure import centroid_delta, corwin_schultz_spread, log_returns
from cq.research.split import to_ms
from scripts.diagnose_coordinate import (
    EXPLORE_END,
    EXPLORE_START,
    INST_ID,
    SCALES,
    TIMEFRAME,
)

LAGS = (1, 2, 3, 4, 6, 8)
DEFAULT_OUT = Path("reports/research/doge_dollar_clock_posthoc.json")


def _aggregate(values: np.ndarray, ends: np.ndarray) -> np.ndarray:
    starts = np.concatenate(([0], ends[:-1]))
    return np.add.reduceat(values[: int(ends[-1])], starts)


def _t_stat(rho: float, n: int) -> float:
    """Approximate t for a Spearman rho; only a magnitude cue, not a p-value."""
    if n < 4 or not np.isfinite(rho) or abs(rho) >= 1.0:
        return float("nan")
    return float(rho * np.sqrt((n - 2) / (1 - rho**2)))


def run(db_path: str, out_path: Path) -> dict:
    with Store(db_path) as store:
        frame = store.load_ohlcv(INST_ID, TIMEFRAME, to_ms(EXPLORE_START), to_ms(EXPLORE_END))
    returns = log_returns(frame["close"].to_numpy(np.float64))
    aligned = frame.iloc[1:]
    quote_volume = aligned["quote_volume"].to_numpy(np.float64)

    scales: dict[str, dict] = {}
    for label, factor in SCALES.items():
        target_count = len(aligned) // factor
        solution = solve_bucket_size(quote_volume, target_count)
        edges = bucket_edges(quote_volume, solution.target_value)
        dollar = aggregate_by_edges(aligned, edges)
        calendar = aggregate_calendar(aligned, factor)
        dollar_r = _aggregate(returns, edges)
        calendar_r = _aggregate(returns, np.arange(factor, target_count * factor + 1, factor))

        # Lag profile. The bounce argument in RESULTS 3.2 rests on lag 1 being
        # anomalous relative to its neighbours, so the neighbours must be shown.
        lags = {}
        for lag in LAGS:
            rd = rank_autocorrelation(dollar_r, lag)
            rc = rank_autocorrelation(calendar_r, lag)
            lags[str(lag)] = {
                "dollar": rd,
                "calendar": rc,
                "dollar_t": _t_stat(rd, dollar_r.size),
                "calendar_t": _t_stat(rc, calendar_r.size),
            }

        # delta_r_squared: pre-registered corroboration, not executed by the
        # diagnosis runner. Reported here to close that gap.
        def delta_pair(bars):
            d = centroid_delta(
                bars["high"].to_numpy(),
                bars["low"].to_numpy(),
                bars["close"].to_numpy(),
                bars["quote_volume"].to_numpy(),
                bars["volume"].to_numpy(),
            )
            return d[:-1], log_returns(bars["close"].to_numpy())

        dd, df_ = delta_pair(dollar)
        cd, cf = delta_pair(calendar)

        scales[label] = {
            "lags": lags,
            "variance_ratio": {
                str(q): {
                    "dollar": variance_ratio(dollar_r, q),
                    "calendar": variance_ratio(calendar_r, q),
                }
                for q in (2, 4, 8)
            },
            "delta_r_squared": {
                "dollar": delta_r_squared(dd, df_),
                "calendar": delta_r_squared(cd, cf),
            },
            # The design's headline novelty is bucket duration itself. The
            # diagnosis tested the coupling premise against inverse hourly
            # turnover, a proxy; this uses the durations the bucketing already
            # produced.
            "coupling_true_duration": _coupling(aligned, dollar, edges),
        }

    # Null centring: the block bootstrap destroys dependence longer than the
    # block, which moves the null's centre, not just its width. RESULTS 5 only
    # checked the width.
    centring = {}
    factor = SCALES["4h"]
    target_count = len(aligned) // factor
    solution = solve_bucket_size(quote_volume, target_count)
    edges = {factor: bucket_edges(quote_volume, solution.target_value)}
    for block in (12.0, 576.0, 2880.0):
        observed, null = paired_null_draws(
            returns_5m=returns,
            quote_volume=quote_volume,
            edges_by_scale=edges,
            calendar_factors=[factor],
            measure="rank_autocorrelation",
            draws=300,
            mean_block=block,
            seed=0,
        )
        centring[str(int(block))] = {
            "observed": float(observed[0]),
            "null_mean": float(null.mean()),
            "null_sd": float(null.std(ddof=1)),
            "z_uncentred": float(observed[0] / null.std(ddof=1)),
            "z_centred": float((observed[0] - null.mean()) / null.std(ddof=1)),
            "p_value": combine_scales(observed, null).p_value,
        }

    result = {
        "label": "doge-dollar-clock-posthoc-v1",
        "note": "Post-hoc. Changes no pre-registered verdict.",
        "scales": scales,
        "null_centring_4h": centring,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def _coupling(aligned, dollar, edges: np.ndarray) -> dict:
    """Spread against the bucket's own calendar duration."""
    spread = corwin_schultz_spread(aligned["high"].to_numpy(), aligned["low"].to_numpy())
    # spread[i] is estimated from bars i and i+1; assign it to bar i, then take
    # each bucket's mean over the bars it owns (dropping the final bucket, whose
    # last bar has no successor).
    ends = np.asarray(edges, dtype=np.int64)
    usable = ends[ends <= spread.size]
    if usable.size < 2:
        return {"spearman_spread_vs_duration": float("nan"), "buckets": 0}
    starts = np.concatenate(([0], usable[:-1]))
    counts = usable - starts
    bucket_spread = np.add.reduceat(spread[: int(usable[-1])], starts) / counts
    duration = dollar["duration_ms"].to_numpy()[: usable.size] / 3_600_000.0
    return {
        "spearman_spread_vs_duration": rank_predictive_power(duration, bucket_spread),
        "median_duration_hours": float(np.median(duration)),
        "median_spread_bps": float(np.median(bucket_spread) * 10_000),
        "buckets": int(usable.size),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    args = parser.parse_args(argv)
    result = run(args.db, Path(args.out))

    print("=== rank autocorrelation by lag (dollar / calendar) ===")
    for label in SCALES:
        row = " ".join(
            f"L{lag}:{result['scales'][label]['lags'][str(lag)]['dollar']:+.4f}/"
            f"{result['scales'][label]['lags'][str(lag)]['calendar']:+.4f}"
            for lag in LAGS
        )
        print(f"  {label:>4} {row}")
    print("\n=== variance ratio q=8 (dollar / calendar) ===")
    for label in SCALES:
        vr = result["scales"][label]["variance_ratio"]["8"]
        print(f"  {label:>4} {vr['dollar']:.3f} / {vr['calendar']:.3f}")
    print("\n=== delta R^2 (dollar / calendar) ===")
    for label in SCALES:
        rs = result["scales"][label]["delta_r_squared"]
        print(f"  {label:>4} {rs['dollar']:.5f} / {rs['calendar']:.5f}")
    print("\n=== coupling premise vs TRUE bucket duration ===")
    for label in SCALES:
        c = result["scales"][label]["coupling_true_duration"]
        print(
            f"  {label:>4} spearman={c['spearman_spread_vs_duration']:+.4f} "
            f"median_dur={c['median_duration_hours']:.2f}h "
            f"median_spread={c['median_spread_bps']:.2f}bps"
        )
    print("\n=== null centring at 4h ===")
    for block, c in result["null_centring_4h"].items():
        print(
            f"  block={block:>5} obs={c['observed']:+.5f} null_mean={c['null_mean']:+.5f} "
            f"sd={c['null_sd']:.5f} z_uncentred={c['z_uncentred']:+.2f} "
            f"z_centred={c['z_centred']:+.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
