"""D-phase runner: does a dollar clock buy predictability a calendar clock lacks?

Produces a verdict, not a strategy. Nothing here computes a return, a position,
or a cost — the point is to find out whether the coordinate change is worth
building on before any of that exists. A CLOSED verdict is a publishable result:
it says DOGE spot 5m lacks structure in two orthogonal coordinate systems, which
is new evidence rather than a sixteenth variant of an old trigger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.coordinate_diagnostics import (
    SIDAK_ALPHA,
    combine_scales,
    delta_paired_null_draws,
    direction_hit_rate,
    evaluate_gates,
    excess_kurtosis,
    paired_null_draws,
    rank_autocorrelation,
    rank_predictive_power,
    select_block_length,
    variance_ratio,
)
from cq.research.dollar_clock import (
    BAR_MS,
    aggregate_by_edges,
    aggregate_calendar,
    bucket_edges,
    solve_bucket_size,
)
from cq.research.microstructure import centroid_delta, corwin_schultz_spread, log_returns
from cq.research.split import ProtocolError, to_ms

INST_ID = "DOGE-USDT"
TIMEFRAME = "5m"
EXPLORE_START = "2021-01-01"
EXPLORE_END = "2025-06-01"
SCALES = {"15m": 3, "1h": 12, "4h": 48, "12h": 144}
PRIMARY_MEASURES = ("rank_autocorrelation", "hit_rate", "delta_power")
DRAWS = 2000
SEED = 0
DEFAULT_OUT = Path("reports/research/doge_dollar_clock_diagnose.json")


def assert_contiguous(frame: pd.DataFrame) -> None:
    """Refuse a gapped series instead of quietly diagnosing a different one."""
    if frame.empty:
        raise ProtocolError("no bars loaded")
    stamps = frame.index.astype("int64") // 1_000_000
    gaps = np.diff(stamps)
    if not np.all(gaps == BAR_MS):
        bad = int(np.sum(gaps != BAR_MS))
        raise ProtocolError(f"series is not contiguous: {bad} gap(s) at 5m spacing")
    span_days = (stamps[-1] + BAR_MS - stamps[0]) / (86_400_000)
    expected = round(span_days * 288)
    if len(frame) != expected:
        raise ProtocolError(f"expected {expected} contiguous bars, loaded {len(frame)}")


def fingerprint(frame: pd.DataFrame) -> str:
    """Content hash so a later run cannot silently diagnose different data."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(frame.index.astype("int64").to_numpy()).tobytes())
    for column in ("open", "high", "low", "close", "volume", "quote_volume"):
        digest.update(np.ascontiguousarray(frame[column].to_numpy(np.float64)).tobytes())
    return digest.hexdigest()[:16]


def _delta_and_forward(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Aligned (delta_t, r_{t+1}) for aggregated bars, dropping the last bar."""
    delta = centroid_delta(
        bars["high"].to_numpy(),
        bars["low"].to_numpy(),
        bars["close"].to_numpy(),
        bars["quote_volume"].to_numpy(),
        bars["volume"].to_numpy(),
    )
    forward = log_returns(bars["close"].to_numpy())
    return delta[:-1], forward


def run(db_path: str, out_path: Path) -> dict:
    with Store(db_path) as store:
        frame = store.load_ohlcv(INST_ID, TIMEFRAME, to_ms(EXPLORE_START), to_ms(EXPLORE_END))
    assert_contiguous(frame)

    # Alignment, and it is load-bearing. `log_returns` yields one value fewer
    # than there are bars: returns[i] is the return OF bar i+1. `bucket_edges`
    # runs on turnover and emits BAR indices. Slicing returns with bar indices
    # therefore shifts every bucket by one bar -- and no meta-test can catch it,
    # because under the null returns and turnover are uncoupled either way, so a
    # shifted null is still a valid null. Dropping the first bar makes the two
    # arrays index-identical: returns[i] is exactly bar i of `aligned`.
    returns = log_returns(frame["close"].to_numpy(np.float64))
    aligned = frame.iloc[1:]
    if len(aligned) != returns.size:
        raise ProtocolError(f"alignment broken: {len(aligned)} bars vs {returns.size} returns")
    quote_volume = aligned["quote_volume"].to_numpy(np.float64)
    block = select_block_length(returns)

    edges_by_scale: dict[int, np.ndarray] = {}
    fidelity = {}
    for label, factor in SCALES.items():
        target_count = len(aligned) // factor
        solution = solve_bucket_size(quote_volume, target_count)
        edges = bucket_edges(quote_volume, solution.target_value)
        edges_by_scale[factor] = edges
        starts = np.concatenate(([0], edges[:-1])) if edges.size else np.empty(0, np.int64)
        sums = np.add.reduceat(quote_volume, starts) if edges.size else np.empty(0)
        fidelity[label] = {
            "target_value": solution.target_value,
            "buckets": int(solution.count),
            "calendar_bars": int(target_count),
            "converged": bool(solution.converged),
            "bucket_turnover_p5": float(np.percentile(sums, 5)) if sums.size else None,
            "bucket_turnover_p50": float(np.percentile(sums, 50)) if sums.size else None,
            "bucket_turnover_p95": float(np.percentile(sums, 95)) if sums.size else None,
            "single_bar_buckets": float(np.mean(np.diff(np.concatenate(([0], edges))) == 1))
            if edges.size
            else None,
        }

    factors = list(SCALES.values())
    combined: dict[str, float] = {}
    agreement: dict[str, int] = {}
    per_measure: dict[str, dict] = {}

    for measure in ("rank_autocorrelation", "hit_rate"):
        observed, null = paired_null_draws(
            returns_5m=returns,
            quote_volume=quote_volume,
            edges_by_scale=edges_by_scale,
            calendar_factors=factors,
            measure=measure,
            draws=DRAWS,
            mean_block=float(block),
            seed=SEED,
        )
        pooled = combine_scales(observed, null)
        combined[measure] = pooled.p_value
        agreement[measure] = pooled.sign_agreement
        per_measure[measure] = {
            "deltas": observed.tolist(),
            "statistic": pooled.statistic,
            "p_value": pooled.p_value,
            "sign_agreement": pooled.sign_agreement,
        }

    dollar_delta, dollar_forward, calendar_delta, calendar_forward = {}, {}, {}, {}
    for factor in factors:
        dollar_delta[factor], dollar_forward[factor] = _delta_and_forward(
            aggregate_by_edges(aligned, edges_by_scale[factor])
        )
        calendar_delta[factor], calendar_forward[factor] = _delta_and_forward(
            aggregate_calendar(aligned, factor)
        )

    delta_observed, delta_null = delta_paired_null_draws(
        dollar_delta=dollar_delta,
        dollar_forward=dollar_forward,
        calendar_delta=calendar_delta,
        calendar_forward=calendar_forward,
        factors=factors,
        draws=DRAWS,
        mean_block=float(block),
        seed=SEED,
    )
    pooled_delta = combine_scales(delta_observed, delta_null)
    combined["delta_power"] = pooled_delta.p_value
    agreement["delta_power"] = pooled_delta.sign_agreement
    per_measure["delta_power"] = {
        "deltas": delta_observed.tolist(),
        "statistic": pooled_delta.statistic,
        "p_value": pooled_delta.p_value,
        "sign_agreement": pooled_delta.sign_agreement,
    }

    corroboration = {}
    kurtosis_reduced = 0
    for label, factor in SCALES.items():
        dollar = aggregate_by_edges(aligned, edges_by_scale[factor])
        calendar = aggregate_calendar(aligned, factor)
        dollar_r = log_returns(dollar["close"].to_numpy())
        calendar_r = log_returns(calendar["close"].to_numpy())
        k_dollar = excess_kurtosis(dollar_r)
        k_calendar = excess_kurtosis(calendar_r)
        kurtosis_reduced += int(k_dollar < k_calendar)
        corroboration[label] = {
            "kurtosis_dollar": k_dollar,
            "kurtosis_calendar": k_calendar,
            "variance_ratio_dollar": {str(q): variance_ratio(dollar_r, q) for q in (2, 4, 8)},
            "variance_ratio_calendar": {str(q): variance_ratio(calendar_r, q) for q in (2, 4, 8)},
            "hit_rate_dollar": direction_hit_rate(dollar_r).rate,
            "hit_rate_calendar": direction_hit_rate(calendar_r).rate,
            "rank_autocorr_dollar": rank_autocorrelation(dollar_r),
            "rank_autocorr_calendar": rank_autocorrelation(calendar_r),
            "median_duration_hours": float(np.median(dollar["duration_ms"])) / 3_600_000,
        }

    # D4: the coupling premise the three-layer narrative rests on.
    spread = corwin_schultz_spread(aligned["high"].to_numpy(), aligned["low"].to_numpy())
    hourly = aggregate_calendar(aligned, 12)
    hourly_spread = (
        np.add.reduceat(
            spread[: (len(spread) // 12) * 12], np.arange(0, (len(spread) // 12) * 12, 12)
        )
        / 12.0
    )
    duration_proxy = 1.0 / hourly["quote_volume"].to_numpy()[: hourly_spread.size]
    premise = {
        "spread_vs_inverse_turnover_spearman": rank_predictive_power(duration_proxy, hourly_spread),
        "median_spread_bps": float(np.median(spread) * 10_000),
    }

    report = evaluate_gates(
        combined=combined,
        sign_agreement=agreement,
        kurtosis_reduced_scales=kurtosis_reduced,
        n_scales=len(SCALES),
    )

    result = {
        "label": "doge-dollar-clock-diagnosis-v1",
        "window": {"start": EXPLORE_START, "end": EXPLORE_END},
        "bars": len(frame),
        "bars_aligned": len(aligned),
        "fingerprints": {"ohlcv": fingerprint(frame)},
        "versions": {
            "scales": SCALES,
            "draws": DRAWS,
            "seed": SEED,
            "block_length": block,
            "sidak_alpha": SIDAK_ALPHA,
        },
        "fidelity": fidelity,
        "measures": per_measure,
        "corroboration": corroboration,
        "coupling_premise": premise,
        "gates": {
            "g1_significance": report.g1_passed,
            "g2_kurtosis_sanity": report.g2_passed,
            "g3_sign_consistency": report.g3_passed,
            "kurtosis_reduced_scales": kurtosis_reduced,
            "winning_measure": report.winning_measure,
        },
        "verdict": report.verdict,
        "holdout_recorded": False,
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
    print(f"verdict={result['verdict']} bars={result['bars']}")
    print(f"fingerprint={result['fingerprints']['ohlcv']}")
    for name, payload in result["measures"].items():
        print(
            f"  {name:<22} p={payload['p_value']:.4f} "
            f"signs={payload['sign_agreement']}/{len(SCALES)}"
        )
    print(f"gates: {result['gates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
