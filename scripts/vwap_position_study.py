"""Does the VWAP position inside a bar predict the next bar, beyond close position?

Implements `docs/research/doge-5m/VWAP_POSITION_PROTOCOL_2026-07-31.md`
verbatim. That protocol was frozen before this script was written: every
threshold, the null design, the discriminant table and the five-way verdict
are pre-registered there and must not be retuned after seeing a result.

Context (protocol Sec. 1): the prior design claimed `delta = (C - VWAP)/(H -
L)` was near-orthogonal to close position (corr 0.1415) and built on that.
A later audit found the coupling actually fed into the pipeline was `delta =
close_position - vwap_position`, and because VWAP position's variance is only
38% of close position's, delta correlates 0.94 with close position -- not
orthogonal at all. The genuinely orthogonal quantity is VWAP position itself,
`v_t = (VWAP_t - L_t) / (H_t - L_t)`, which had never been tested on its own.
This script tests it, controlling for close position `c_t = (C_t - L_t) /
(H_t - L_t)` -- the quantity every prior study in this repository has already
used -- so the result is `v`'s increment over `c`, not a restatement of it.

Run: .venv/bin/python scripts/vwap_position_study.py --db data/cq.db
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.coordinate_diagnostics import (
    combine_scales,
    rank_partial,
    rank_predictive_power,
    stationary_bootstrap_indices,
)
from cq.research.dollar_clock import (
    aggregate_by_edges,
    aggregate_calendar,
    bucket_edges,
    solve_bucket_size,
)
from cq.research.microstructure import log_returns, vwap_position
from cq.research.split import ProtocolError, to_ms
from scripts.diagnose_coordinate import (
    EXPLORE_END,
    EXPLORE_START,
    INST_ID,
    SCALES,
    TIMEFRAME,
    assert_contiguous,
    fingerprint,
)

DRAWS = 2000
SEED = 0
BLOCK = 12.0
SIGNIFICANCE_ALPHA = 0.05
BAR_MS = 300_000

# Sec. 4: the window is frozen and the data behind it must not have moved
# since the protocol was written. A mismatch here means the run is diagnosing
# different data than the one the thresholds below were derived for.
EXPECTED_FINGERPRINT = "12b8ca59c15fc519"

# Sec. 7 item 2: corr(v, c) on calendar 5m, reproduced from
# `DOLLAR_CLOCK_DURATION_2026-07-31.md` Sec. 5 ("corr(VWAP位置, close位置) =
# +0.1374"). The protocol states this only as "约为 0.137" (approximately),
# without a numeric tolerance; 0.02 is this script's own choice for how much
# slack "approximately" allows -- wide enough to survive incidental
# implementation differences (e.g. exact NaN-dropping order), tight enough
# that only a genuine pipeline divergence from the prior measurement would
# trip it.
CORR_V_C_5M_EXPECTED = 0.137
CORR_V_C_5M_TOLERANCE = 0.02

DEFAULT_OUT = Path("reports/research/doge_vwap_position.json")

# Sec. 5: minimum |M| for the signal to clear one round-trip cost at that
# scale (3.39 bps Corwin-Schultz median spread / sigma_r at that scale).
# Verbatim from the protocol; not a computed value in this script.
TRADEABLE_LOWER_BOUND = {"15m": 0.0433, "1h": 0.0228, "4h": 0.0114, "12h": 0.0067}


def _required(n_scales: int) -> int:
    """The `>= 3/4` (or `>= 2/4`) thresholds, generalised to any scale count."""
    return int(np.ceil(0.75 * n_scales))


def _v_and_c(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(v, c) for one set of bars, undefined together per protocol Sec. 1.

    `c = (C - L) / (H - L)` never touches volume, but the protocol declares
    it undefined under the same condition as `v` (H == L or zero volume): a
    zero-volume bar is a degenerate print, and admitting `c` there while `v`
    is dropped would desynchronise the pair the main statistic needs matched.
    `v`'s own NaN (from `vwap_position`) is therefore reused directly as the
    usability mask for `c`, rather than recomputed from `span > 0` alone.
    """
    high = bars["high"].to_numpy(np.float64)
    low = bars["low"].to_numpy(np.float64)
    close = bars["close"].to_numpy(np.float64)
    quote_volume = bars["quote_volume"].to_numpy(np.float64)
    volume = bars["volume"].to_numpy(np.float64)

    v = vwap_position(high, low, quote_volume, volume)
    span = high - low
    usable = np.isfinite(v)
    c = np.full_like(high, np.nan)
    np.divide(close - low, span, out=c, where=usable)
    return v, c


def _aligned_v_c_forward(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """(v_t, c_t, r_{t+1}) with undefined bars dropped, and the drop fraction.

    `v`/`c` are computed on every bar, then the last one is dropped (it has
    no forward return) before the undefined-bar filter is applied -- the same
    alignment convention `diagnose_coordinate._delta_and_forward` uses.
    """
    v, c = _v_and_c(bars)
    forward = log_returns(bars["close"].to_numpy(np.float64))
    v_t, c_t = v[:-1], c[:-1]
    usable = np.isfinite(v_t) & np.isfinite(c_t)
    drop_fraction = float(1.0 - usable.mean())
    return v_t[usable], c_t[usable], forward[usable], drop_fraction


@dataclass(frozen=True)
class ClockAnalysis:
    """One clock's evidence across all four scales."""

    per_scale: dict
    m_by_scale: dict
    combined_p: float
    combined_statistic: float
    sign_agreement: int


def _analyse_clock(bars_by_scale: dict[str, pd.DataFrame], seed: int) -> ClockAnalysis:
    """Main statistic M, its null p-value, and the plain c-vs-return check, per scale.

    The null (protocol Sec. 3.3) block-bootstraps `v` only; `r` and `c` stay
    frozen. One RNG is threaded through every scale of this clock in a fixed
    order, so the resulting (draws x scales) null matrix is drawn from a
    single seeded stream -- the "joint sampling" `combine_scales` expects to
    pool across scales.
    """
    rng = np.random.default_rng(seed)
    per_scale: dict[str, dict] = {}
    m_by_scale: dict[str, float] = {}
    m_array: list[float] = []
    null_matrix = np.empty((DRAWS, len(bars_by_scale)), dtype=np.float64)

    for index, (label, bars) in enumerate(bars_by_scale.items()):
        v_f, c_f, r_f, drop_fraction = _aligned_v_c_forward(bars)
        m = rank_partial(v_f, r_f, c_f)

        null = np.empty(DRAWS, dtype=np.float64)
        for draw in range(DRAWS):
            shuffled = v_f[stationary_bootstrap_indices(v_f.size, BLOCK, rng)]
            null[draw] = rank_partial(shuffled, r_f, c_f)
        extreme = int(np.sum(np.abs(null) >= abs(m)))
        p_value = (extreme + 1) / (DRAWS + 1)

        c_power = rank_predictive_power(c_f, r_f)

        per_scale[label] = {
            "M": m,
            "p_value": p_value,
            "n": int(v_f.size),
            "drop_fraction": drop_fraction,
            "c_predictive_power": c_power,
        }
        m_by_scale[label] = m
        m_array.append(m)
        null_matrix[:, index] = null

    combined = combine_scales(np.asarray(m_array, dtype=np.float64), null_matrix)
    return ClockAnalysis(
        per_scale=per_scale,
        m_by_scale=m_by_scale,
        combined_p=combined.p_value,
        combined_statistic=combined.statistic,
        sign_agreement=combined.sign_agreement,
    )


@dataclass(frozen=True)
class GateReport:
    """The pre-registered G1-G4 verdict (protocol Sec. 5-6)."""

    g1_passed: bool
    g2_passed: bool
    g3_passed: bool
    g4_passed: bool
    g4_scales_passed: int
    verdict: str  # TRADEABLE-LEAD | REAL-BUT-SUBTHRESHOLD | ARTEFACT | CLOSED


def _evaluate_gates(
    dollar: ClockAnalysis, calendar: ClockAnalysis, scale_labels: list[str]
) -> GateReport:
    """G1-G4 and the resulting verdict, exactly as tabulated in protocol Sec. 6.

    Does not decide INVALID -- that is layered on afterwards from the Sec. 7
    sanity checks, which need this report's gate values to already exist.
    """
    required = _required(len(scale_labels))

    g1_passed = dollar.combined_p <= SIGNIFICANCE_ALPHA
    g2_passed = dollar.sign_agreement >= required

    sign_matches = sum(
        1
        for label in scale_labels
        if np.sign(dollar.m_by_scale[label]) == np.sign(calendar.m_by_scale[label])
    )
    g3_passed = sign_matches >= required

    g4_scales_passed = sum(
        1 for label in scale_labels if abs(dollar.m_by_scale[label]) >= TRADEABLE_LOWER_BOUND[label]
    )
    g4_passed = g4_scales_passed >= 2

    if not (g1_passed and g2_passed):
        verdict = "CLOSED"
    elif not g3_passed:
        verdict = "ARTEFACT"
    elif not g4_passed:
        verdict = "REAL-BUT-SUBTHRESHOLD"
    else:
        verdict = "TRADEABLE-LEAD"

    return GateReport(
        g1_passed=g1_passed,
        g2_passed=g2_passed,
        g3_passed=g3_passed,
        g4_passed=g4_passed,
        g4_scales_passed=g4_scales_passed,
        verdict=verdict,
    )


def _discriminant(dollar: ClockAnalysis, calendar: ClockAnalysis) -> dict:
    """The Sec. 3.2 discriminant table, evaluated on each clock's combined statistic."""
    dollar_significant = dollar.combined_p <= SIGNIFICANCE_ALPHA
    calendar_significant = calendar.combined_p <= SIGNIFICANCE_ALPHA
    same_sign = (dollar.combined_statistic > 0) == (calendar.combined_statistic > 0)

    if dollar_significant and calendar_significant and same_sign:
        classification = "REAL_SIGNAL"
    elif not dollar_significant and calendar_significant:
        classification = "SPREAD_BOUNCE_ARTEFACT"
    elif dollar_significant and not (calendar_significant and same_sign):
        classification = "AMBIGUOUS"
    else:
        classification = "NO_SIGNAL"

    return {
        "dollar_significant": dollar_significant,
        "calendar_significant": calendar_significant,
        "same_sign": same_sign,
        "classification": classification,
    }


def _sanity_checks(
    dollar: ClockAnalysis,
    calendar: ClockAnalysis,
    scale_labels: list[str],
    aligned: pd.DataFrame,
) -> dict:
    """Protocol Sec. 7: three checks, all must pass or the run is INVALID."""
    required = _required(len(scale_labels))

    stronger = sum(
        1
        for label in scale_labels
        if abs(calendar.per_scale[label]["c_predictive_power"])
        > abs(dollar.per_scale[label]["c_predictive_power"])
    )
    spread_bounce_signature = {
        "calendar_stronger_scales": stronger,
        "required": required,
        "passed": stronger >= required,
    }

    v_5m, c_5m = _v_and_c(aligned)
    usable = np.isfinite(v_5m) & np.isfinite(c_5m)
    corr = float(stats.spearmanr(v_5m[usable], c_5m[usable]).statistic)
    corr_v_c_calendar_5m = {
        "value": corr,
        "expected": CORR_V_C_5M_EXPECTED,
        "tolerance": CORR_V_C_5M_TOLERANCE,
        "passed": abs(corr - CORR_V_C_5M_EXPECTED) <= CORR_V_C_5M_TOLERANCE,
    }

    # Fingerprint failure raises before any of this runs (see `run`), so by
    # construction it is always True here; recorded anyway so the sanity
    # block is a complete record of all three Sec. 7 checks in one place.
    fingerprint_ok = True

    all_passed = (
        spread_bounce_signature["passed"] and corr_v_c_calendar_5m["passed"] and fingerprint_ok
    )
    return {
        "spread_bounce_signature": spread_bounce_signature,
        "corr_v_c_calendar_5m": corr_v_c_calendar_5m,
        "fingerprint_ok": fingerprint_ok,
        "all_passed": all_passed,
    }


def run(db_path: str, out_path: Path) -> dict:
    with Store(db_path) as store:
        frame = store.load_ohlcv(INST_ID, TIMEFRAME, to_ms(EXPLORE_START), to_ms(EXPLORE_END))
    expected_bars = (to_ms(EXPLORE_END) - to_ms(EXPLORE_START)) // BAR_MS
    assert_contiguous(frame, expected_bars=expected_bars)

    fp = fingerprint(frame)
    if fp != EXPECTED_FINGERPRINT:
        raise ProtocolError(
            f"fingerprint mismatch: expected {EXPECTED_FINGERPRINT}, got {fp}. "
            "The data behind the frozen protocol has changed; re-derive the "
            "protocol's thresholds before trusting any result from this run."
        )

    # Alignment (protocol Sec. 4): dropping the first bar makes `returns[i]`
    # exactly the return OF `aligned` bar i, matching `diagnose_coordinate.run`.
    returns = log_returns(frame["close"].to_numpy(np.float64))
    aligned = frame.iloc[1:]
    if len(aligned) != returns.size:
        raise ProtocolError(f"alignment broken: {len(aligned)} bars vs {returns.size} returns")
    quote_volume = aligned["quote_volume"].to_numpy(np.float64)

    dollar_bars: dict[str, pd.DataFrame] = {}
    calendar_bars: dict[str, pd.DataFrame] = {}
    fidelity: dict[str, dict] = {}
    for label, factor in SCALES.items():
        target_count = len(aligned) // factor
        solution = solve_bucket_size(quote_volume, target_count)
        edges = bucket_edges(quote_volume, solution.target_value)
        dollar_bars[label] = aggregate_by_edges(aligned, edges)
        calendar_bars[label] = aggregate_calendar(aligned, factor)
        fidelity[label] = {
            "target_value": solution.target_value,
            "buckets": int(solution.count),
            "calendar_bars": int(target_count),
            "converged": bool(solution.converged),
        }

    dollar = _analyse_clock(dollar_bars, SEED)
    calendar = _analyse_clock(calendar_bars, SEED)

    scale_labels = list(SCALES)
    gates = _evaluate_gates(dollar, calendar, scale_labels)
    discriminant = _discriminant(dollar, calendar)
    sanity = _sanity_checks(dollar, calendar, scale_labels, aligned)

    verdict = gates.verdict if sanity["all_passed"] else "INVALID"

    result = {
        "label": "doge-vwap-position-v1",
        "window": {"start": EXPLORE_START, "end": EXPLORE_END},
        "bars": len(frame),
        "bars_aligned": len(aligned),
        "fingerprints": {"ohlcv": fp},
        "versions": {
            "scales": SCALES,
            "draws": DRAWS,
            "seed": SEED,
            "block": BLOCK,
            "significance_alpha": SIGNIFICANCE_ALPHA,
            "tradeable_lower_bound": TRADEABLE_LOWER_BOUND,
        },
        "fidelity": fidelity,
        "clocks": {
            "dollar": {
                "scales": dollar.per_scale,
                "combined_p": dollar.combined_p,
                "combined_statistic": dollar.combined_statistic,
                "sign_agreement": dollar.sign_agreement,
            },
            "calendar": {
                "scales": calendar.per_scale,
                "combined_p": calendar.combined_p,
                "combined_statistic": calendar.combined_statistic,
                "sign_agreement": calendar.sign_agreement,
            },
        },
        "discriminant": discriminant,
        "sanity": sanity,
        "gates": {
            "g1_significance": gates.g1_passed,
            "g2_sign_consistency": gates.g2_passed,
            "g3_discriminant_sign_match": gates.g3_passed,
            "g4_effect_size": gates.g4_passed,
            "g4_scales_passed": gates.g4_scales_passed,
        },
        "verdict": verdict,
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
    for clock in ("dollar", "calendar"):
        payload = result["clocks"][clock]
        print(
            f"  {clock:<8} combined_p={payload['combined_p']:.4f} "
            f"signs={payload['sign_agreement']}/4"
        )
        for label, scale in payload["scales"].items():
            print(
                f"    {label:>4} M={scale['M']:+.4f} p={scale['p_value']:.4f} "
                f"n={scale['n']} drop={scale['drop_fraction']:.3f}"
            )
    print(f"discriminant: {result['discriminant']['classification']}")
    print(f"sanity: {result['sanity']['all_passed']}")
    print(f"gates: {result['gates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
