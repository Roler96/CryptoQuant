"""D4 items 2-4: what bucket duration actually carries.

The diagnosis (`scripts/diagnose_coordinate.py`) left three of the four D4
items unexecuted, including the one the design called its headline novelty:
bucket duration. Duration is a variable that exists *only* on the dollar
clock -- on the calendar clock it is constant by construction -- so it is the
concrete form of the design's claim that once turnover per bucket is held
fixed, the information about activity moves into how long the bucket took.

This is diagnostic, not adjudication. D4 carries no gate, and nothing here
changes the pre-registered verdict. Findings are leads, not conclusions.

Three things are measured, and the middle one is the point:

* Direction: Spearman(dt, next return). Duration is a pure intensity measure,
  decoupled from sign, so this should be ~0. It is a sanity check -- a
  non-trivial value would signal an artefact, not an edge.
* Volatility, and whether it is incremental: a short bucket means turnover
  arrived fast, which means the period was active, which means volatility was
  high. That duration predicts next-bucket volatility is therefore nearly
  definitional and worth little on its own. What matters is whether it adds
  anything once past volatility is already known, so the headline number is
  the rank-partial correlation controlling for |r_t|.
* Persistence: the autocorrelation of duration itself, i.e. how long an
  activity regime lasts in event time.

Run: .venv/bin/python scripts/dollar_clock_duration.py --db data/cq.db
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import stats

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.coordinate_diagnostics import (
    rank_autocorrelation,
    rank_predictive_power,
    stationary_bootstrap_indices,
)
from cq.research.dollar_clock import (
    aggregate_by_edges,
    aggregate_calendar,
    bucket_edges,
    solve_bucket_size,
)
from cq.research.microstructure import centroid_delta, log_returns
from cq.research.split import to_ms
from scripts.diagnose_coordinate import (
    EXPLORE_END,
    EXPLORE_START,
    INST_ID,
    SCALES,
    TIMEFRAME,
)

DRAWS = 2000
SEED = 0
BLOCK = 12.0
DEFAULT_OUT = Path("reports/research/doge_dollar_clock_duration.json")


def _ranks(values: np.ndarray) -> np.ndarray:
    return stats.rankdata(values)


def rank_partial(x: np.ndarray, y: np.ndarray, control: np.ndarray) -> float:
    """Spearman correlation of x and y after removing what `control` explains.

    Both variables are ranked, then linearly detrended against the ranked
    control, and the residuals correlated. Without this, "duration predicts
    volatility" is close to a restatement of "turnover arrived fast because
    the market was busy".
    """
    rx, ry, rc = _ranks(x), _ranks(y), _ranks(control)
    ones = np.ones_like(rc)
    design = np.column_stack([ones, rc])
    coef_x, *_ = np.linalg.lstsq(design, rx, rcond=None)
    coef_y, *_ = np.linalg.lstsq(design, ry, rcond=None)
    res_x = rx - design @ coef_x
    res_y = ry - design @ coef_y
    if res_x.std() == 0 or res_y.std() == 0:
        return float("nan")
    return float(np.corrcoef(res_x, res_y)[0, 1])


def _null_p(
    statistic: float,
    feature: np.ndarray,
    target: np.ndarray,
    control: np.ndarray | None,
    seed: int,
) -> float:
    """Block-bootstrap the feature, freeze everything else.

    Same shape of null as the diagnosis' delta test: only the coupling under
    examination is broken, the series' own dependence is preserved.
    """
    rng = np.random.default_rng(seed)
    n = feature.size
    extreme = 0
    for _ in range(DRAWS):
        shuffled = feature[stationary_bootstrap_indices(n, BLOCK, rng)]
        drawn = (
            rank_predictive_power(shuffled, target)
            if control is None
            else rank_partial(shuffled, target, control)
        )
        if abs(drawn) >= abs(statistic):
            extreme += 1
    return (extreme + 1) / (DRAWS + 1)


def analyse(bars, returns: np.ndarray, seed: int) -> dict:
    """All duration measures for one clock, on aligned (dt_t, r_{t+1}) pairs."""
    duration = bars["duration_ms"].to_numpy(np.float64)[:-1] / 60_000.0  # minutes
    current = returns[:-1]
    forward = returns[1:]
    abs_forward = np.abs(forward)
    abs_current = np.abs(current)

    direction = rank_predictive_power(duration, forward)
    volatility = rank_predictive_power(duration, abs_forward)
    baseline = rank_predictive_power(abs_current, abs_forward)
    incremental = rank_partial(duration, abs_forward, abs_current)

    return {
        "buckets": int(duration.size),
        "duration_minutes": {
            "p5": float(np.percentile(duration, 5)),
            "p50": float(np.percentile(duration, 50)),
            "p95": float(np.percentile(duration, 95)),
            "max": float(duration.max()),
            "cv": float(duration.std() / duration.mean()),
        },
        "persistence": {str(lag): rank_autocorrelation(duration, lag) for lag in (1, 2, 5, 10)},
        "direction": {
            "spearman": direction,
            "p_value": _null_p(direction, duration, forward, None, seed),
        },
        "volatility_raw": {
            "spearman": volatility,
            "p_value": _null_p(volatility, duration, abs_forward, None, seed + 1),
        },
        "volatility_baseline_abs_r": baseline,
        "volatility_incremental": {
            "partial_spearman": incremental,
            "p_value": _null_p(incremental, duration, abs_forward, abs_current, seed + 2),
        },
    }


def run(db_path: str, out_path: Path) -> dict:
    with Store(db_path) as store:
        frame = store.load_ohlcv(INST_ID, TIMEFRAME, to_ms(EXPLORE_START), to_ms(EXPLORE_END))
    returns = log_returns(frame["close"].to_numpy(np.float64))
    aligned = frame.iloc[1:]
    quote_volume = aligned["quote_volume"].to_numpy(np.float64)

    scales: dict[str, dict] = {}
    for index, (label, factor) in enumerate(SCALES.items()):
        target_count = len(aligned) // factor
        solution = solve_bucket_size(quote_volume, target_count)
        edges = bucket_edges(quote_volume, solution.target_value)
        dollar = aggregate_by_edges(aligned, edges)
        calendar = aggregate_calendar(aligned, factor)

        starts = np.concatenate(([0], edges[:-1]))
        dollar_r = np.add.reduceat(returns[: int(edges[-1])], starts)

        # D4 item 4: delta versus close position, on both clocks. The design
        # measured 0.1415 on calendar 5m and called the two near-orthogonal;
        # this checks whether that survives the clock change.
        def positions(bars):
            high = bars["high"].to_numpy()
            low = bars["low"].to_numpy()
            close = bars["close"].to_numpy()
            span = high - low
            usable = span > 0
            delta = centroid_delta(
                high,
                low,
                close,
                bars["quote_volume"].to_numpy(),
                bars["volume"].to_numpy(),
            )
            close_pos = np.zeros_like(span)
            np.divide(close - low, span, out=close_pos, where=usable)
            return delta[usable], close_pos[usable]

        d_delta, d_close = positions(dollar)
        c_delta, c_close = positions(calendar)

        scales[label] = {
            "duration": analyse(dollar, dollar_r, SEED + index * 10),
            "delta_vs_close_position": {
                "dollar": float(stats.spearmanr(d_delta, d_close).statistic),
                "calendar": float(stats.spearmanr(c_delta, c_close).statistic),
            },
        }

    result = {
        "label": "doge-dollar-clock-duration-v1",
        "note": (
            "D4 items 2-4, diagnostic only. No gate, no verdict change. "
            "Duration exists only on the dollar clock; on the calendar clock "
            "it is constant by construction."
        ),
        "draws": DRAWS,
        "seed": SEED,
        "block": BLOCK,
        "scales": scales,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT), type=Path)
    args = parser.parse_args(argv)
    result = run(args.db, Path(args.out))

    print("=== duration distribution (minutes) ===")
    for label in SCALES:
        d = result["scales"][label]["duration"]["duration_minutes"]
        print(
            f"  {label:>4} p5={d['p5']:8.1f} p50={d['p50']:8.1f} "
            f"p95={d['p95']:9.1f} max={d['max']:10.1f} cv={d['cv']:.2f}"
        )
    print("\n=== duration persistence (rank autocorrelation) ===")
    for label in SCALES:
        p = result["scales"][label]["duration"]["persistence"]
        print(f"  {label:>4} " + "  ".join(f"L{k}={v:+.4f}" for k, v in p.items()))
    print("\n=== direction (sanity: should be ~0) ===")
    for label in SCALES:
        d = result["scales"][label]["duration"]["direction"]
        print(f"  {label:>4} rho={d['spearman']:+.5f}  p={d['p_value']:.4f}")
    print("\n=== volatility: raw vs incremental over |r_t| ===")
    for label in SCALES:
        u = result["scales"][label]["duration"]
        print(
            f"  {label:>4} raw={u['volatility_raw']['spearman']:+.4f} "
            f"(p={u['volatility_raw']['p_value']:.4f})  "
            f"baseline|r_t|={u['volatility_baseline_abs_r']:+.4f}  "
            f"incremental={u['volatility_incremental']['partial_spearman']:+.4f} "
            f"(p={u['volatility_incremental']['p_value']:.4f})"
        )
    print("\n=== D4 item 4: delta vs close position ===")
    for label in SCALES:
        c = result["scales"][label]["delta_vs_close_position"]
        print(f"  {label:>4} dollar={c['dollar']:+.4f}  calendar={c['calendar']:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
