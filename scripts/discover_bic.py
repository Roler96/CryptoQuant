"""Discovery runner for BIC-Majors v1.

Runs the frozen main rule and its six pre-declared neighbours on both legs,
combines them into the equal-weight candidate, and puts the result through the
gates named in `docs/superpowers/specs/2026-07-27-btc-intraday-design.md`.

Reading past the explore boundary requires `--holdout`, which records the
access. An unrecorded peek is indistinguishable from no peek, and the count of
reads is itself the multiple-testing correction.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from cq.context import Series
from cq.core.types import CostModel, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import run_backtest
from cq.research.metrics import compute_metrics, max_drawdown, trades_from_fills
from cq.research.split import (
    FORWARD_FREEZE,
    forward_holdout,
    holdout_access_count,
    record_holdout_access,
    to_ms,
)
from cq.research.stats import sidak_correction
from cq.strategy.bic_majors import FAMILY_TRIALS, FROZEN_VERSIONS, BicMajors

LEGS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
TIMEFRAME = "1h"
BAR_MS = 3_600_000
FUNDING_PERIOD_MS = 8 * 3_600_000
FUNDING_BPS_PER_CROSSING = 1.0
INITIAL_CASH = 10_000.0
NULL_DRAWS = 4000
BOOTSTRAP_DRAWS = 4000

# The search that produced main, declared in the design's section 4.
SEARCH_FAMILY = 33

COST_TIERS = {
    "main": CostModel(fee_bps=5.0, slippage_bps=2.0),
    "stress": CostModel(fee_bps=5.0, slippage_bps=7.0),
    "extreme": CostModel(fee_bps=5.0, slippage_bps=20.0),
}


def spec_for(inst_id: str) -> MarketSpec:
    return MarketSpec(inst_id, "swap", max_leverage=1.0)


def funding_crossings(entry_ts: int, exit_ts: int) -> int:
    """8h settlements crossed while held; epoch aligns to 00/08/16 UTC."""
    return int(exit_ts // FUNDING_PERIOD_MS) - int(entry_ts // FUNDING_PERIOD_MS)


def episodes_from_run(result, series: Series) -> list[dict]:
    """One record per round trip, with funding charged against the return."""
    out = []
    for trade in trades_from_fills(result.fills):
        crossings = funding_crossings(trade.entry_ts, trade.exit_ts)
        funding_bps = crossings * FUNDING_BPS_PER_CROSSING
        gross_bps = trade.return_pct * 1e4
        out.append(
            {
                "entry_ts": trade.entry_ts,
                "exit_ts": trade.exit_ts,
                "side": trade.side,
                "gross_bps": gross_bps,
                "funding_bps": funding_bps,
                "net_bps": gross_bps - funding_bps,
            }
        )
    return out


def run_leg(config, inst_id: str, series: Series, costs: CostModel):
    strategy = BicMajors(config, inst_id=inst_id)
    result = run_backtest(
        strategy,
        series,
        spec_for(inst_id),
        INITIAL_CASH,
        costs=costs,
        sizing=Sizing.ON_ENTRY,
    )
    return strategy, result


def combined_equity(runs: dict[str, object]) -> tuple[np.ndarray, np.ndarray]:
    """Both legs in one account, each at its own 0.25 target weight.

    The legs share capital rather than splitting it, so their per-bar returns
    add: total exposure reaches 0.5 when both are open, which is what the
    frozen rule says. Averaging the two equity curves instead would silently
    halve every position to 0.125 and report a different strategy.
    """
    curves = []
    for _, result in runs.values():
        ts = np.array(result.timestamps, dtype=np.int64)
        eq = np.array(result.equity, dtype=float) / result.initial_cash
        curves.append((ts, eq))
    common = curves[0][0]
    for ts, _ in curves[1:]:
        common = np.intersect1d(common, ts)

    total = np.zeros(len(common))
    for ts, eq in curves:
        aligned = eq[np.searchsorted(ts, common)]
        leg_returns = np.zeros(len(aligned))
        leg_returns[1:] = aligned[1:] / aligned[:-1] - 1.0
        total += leg_returns
    return common, np.cumprod(1.0 + total)


def matched_null(
    series_map: dict[str, Series],
    episodes: list[dict],
    hold_bars: int,
    cost_bps_round_trip: float,
    seed: int,
) -> np.ndarray:
    """Random entries matched on asset, year, count, side and holding length."""
    rng = np.random.default_rng(seed)
    by_key: dict[tuple[str, int, str], int] = defaultdict(int)
    for episode in episodes:
        year = dt.datetime.fromtimestamp(episode["entry_ts"] / 1000, dt.UTC).year
        by_key[(episode["inst_id"], year, episode["side"])] += 1

    pools: dict[tuple[str, int], np.ndarray] = {}
    logo: dict[str, np.ndarray] = {}
    for inst_id, series in series_map.items():
        logo[inst_id] = np.log(series.open)
        years = np.array(
            [dt.datetime.fromtimestamp(t / 1000, dt.UTC).year for t in series.ts]
        )
        limit = len(series.ts) - hold_bars - 1
        for year in np.unique(years):
            pools[(inst_id, int(year))] = np.flatnonzero(
                (years == year) & (np.arange(len(series.ts)) < limit)
            )

    draws = np.empty(NULL_DRAWS)
    for draw in range(NULL_DRAWS):
        values = []
        for (inst_id, year, side), count in by_key.items():
            pool = pools[(inst_id, year)]
            picks = rng.choice(pool, size=count, replace=False)
            sign = 1.0 if side == "long" else -1.0
            moves = sign * (logo[inst_id][picks + hold_bars] - logo[inst_id][picks]) * 1e4
            values.append(moves - cost_bps_round_trip)
        draws[draw] = float(np.concatenate(values).mean())
    return draws


def cluster_ids(episodes: list[dict], tolerance_ms: int = BAR_MS) -> list[int]:
    """Group episodes whose entries land within one bar of each other."""
    order = sorted(range(len(episodes)), key=lambda i: episodes[i]["entry_ts"])
    ids = [0] * len(episodes)
    current = 0
    previous = None
    for position in order:
        ts = episodes[position]["entry_ts"]
        if previous is not None and ts - previous > tolerance_ms:
            current += 1
        ids[position] = current
        previous = ts
    return ids


def cluster_bootstrap(episodes: list[dict], seed: int) -> dict:
    """Resample clusters, not episodes, so co-firing legs travel together."""
    rng = np.random.default_rng(seed)
    ids = cluster_ids(episodes)
    grouped: dict[int, list[float]] = defaultdict(list)
    for cluster, episode in zip(ids, episodes, strict=True):
        grouped[cluster].append(episode["net_bps"])
    keys = list(grouped)
    draws = np.empty(BOOTSTRAP_DRAWS)
    for draw in range(BOOTSTRAP_DRAWS):
        picks = rng.choice(keys, size=len(keys), replace=True)
        draws[draw] = float(np.concatenate([grouped[k] for k in picks]).mean())
    return {
        "clusters": len(keys),
        "p5": float(np.quantile(draws, 0.05)),
        "p50": float(np.median(draws)),
        "p95": float(np.quantile(draws, 0.95)),
    }


def diagnostics(episodes: list[dict]) -> dict:
    """Pre-registered mechanism splits. Reported, never selected on."""
    ids = cluster_ids(episodes)
    sizes = defaultdict(int)
    for cluster in ids:
        sizes[cluster] += 1

    def mean_of(subset: list[dict]) -> dict:
        if not subset:
            return {"n": 0, "net_bps": None}
        return {
            "n": len(subset),
            "net_bps": float(np.mean([e["net_bps"] for e in subset])),
        }

    hours = [dt.datetime.fromtimestamp(e["entry_ts"] / 1000, dt.UTC) for e in episodes]
    return {
        "us_session_h13_h21": mean_of(
            [e for e, h in zip(episodes, hours, strict=True) if 13 <= h.hour <= 21]
        ),
        "asia_h0_h8": mean_of(
            [e for e, h in zip(episodes, hours, strict=True) if 0 <= h.hour <= 8]
        ),
        "weekday": mean_of(
            [e for e, h in zip(episodes, hours, strict=True) if h.weekday() < 5]
        ),
        "weekend": mean_of(
            [e for e, h in zip(episodes, hours, strict=True) if h.weekday() >= 5]
        ),
        "long": mean_of([e for e in episodes if e["side"] == "long"]),
        "short": mean_of([e for e in episodes if e["side"] == "short"]),
        "resonant": mean_of(
            [e for e, c in zip(episodes, ids, strict=True) if sizes[c] > 1]
        ),
        "idiosyncratic": mean_of(
            [e for e, c in zip(episodes, ids, strict=True) if sizes[c] == 1]
        ),
        "per_leg": {
            inst: mean_of([e for e in episodes if e["inst_id"] == inst]) for inst in LEGS
        },
    }


def yearly(episodes: list[dict], stamps: np.ndarray, equity: np.ndarray) -> dict:
    by_year: dict[int, list[float]] = defaultdict(list)
    for episode in episodes:
        year = dt.datetime.fromtimestamp(episode["entry_ts"] / 1000, dt.UTC).year
        by_year[year].append(episode["net_bps"])
    years = np.array([dt.datetime.fromtimestamp(t / 1000, dt.UTC).year for t in stamps])
    out = {}
    for year in sorted(by_year):
        mask = years == year
        curve = equity[mask] / equity[mask][0] if mask.any() else np.array([1.0])
        out[str(year)] = {
            "episodes": len(by_year[year]),
            "mean_net_bps": float(np.mean(by_year[year])),
            "return_pct": float((curve[-1] - 1.0) * 100),
            "max_drawdown_pct": float(max_drawdown(curve) * 100),
        }
    return out


def evaluate(store: Store, start_ms: int, end_ms: int, label: str) -> dict:
    series_map = {
        inst: load_series(store, inst, TIMEFRAME, start_ms, end_ms) for inst in LEGS
    }
    for inst, series in series_map.items():
        gaps = np.flatnonzero(np.diff(series.ts) != BAR_MS)
        if len(gaps):
            raise SystemExit(
                f"{inst} has {len(gaps)} timestamp gap(s) in {label}; "
                "the runner refuses to approximate a frozen protocol"
            )

    report: dict = {
        "label": label,
        "window": {
            "start": dt.datetime.fromtimestamp(start_ms / 1000, dt.UTC).strftime("%Y-%m-%d"),
            "end": dt.datetime.fromtimestamp(end_ms / 1000, dt.UTC).strftime("%Y-%m-%d"),
        },
        "bars": {inst: len(s.ts) for inst, s in series_map.items()},
        "fingerprints": {},
        "versions": {},
    }

    for version, config in FROZEN_VERSIONS.items():
        tiers = {}
        for tier, costs in COST_TIERS.items():
            runs = {
                inst: run_leg(config, inst, series_map[inst], costs) for inst in LEGS
            }
            episodes = []
            for inst, (_, result) in runs.items():
                for episode in episodes_from_run(result, series_map[inst]):
                    episode["inst_id"] = inst
                    episodes.append(episode)
            stamps, equity = combined_equity(runs)
            metrics = compute_metrics(
                [int(t) for t in stamps],
                [float(v) * INITIAL_CASH for v in equity],
                [f for _, r in runs.values() for f in r.fills],
                INITIAL_CASH,
            )
            net = np.array([e["net_bps"] for e in episodes]) if episodes else np.zeros(0)
            entry = {
                "episodes": len(episodes),
                "mean_net_bps": float(net.mean()) if len(net) else 0.0,
                "win_rate": float((net > 0).mean()) if len(net) else 0.0,
                "total_return_pct": float((equity[-1] - 1.0) * 100),
                "max_drawdown_pct": float(max_drawdown(equity) * 100),
                "sharpe": metrics.sharpe,
                "mean_less_best_bps": (
                    float((net.sum() - net.max()) / len(net)) if len(net) else 0.0
                ),
                "gap_chased_entries": 0,
            }
            if tier == "main":
                entry["yearly"] = yearly(episodes, stamps, equity)
                entry["cluster_bootstrap"] = cluster_bootstrap(episodes, seed=20260727)
                if version == "main":
                    entry["diagnostics"] = diagnostics(episodes)
                    round_trip = 2 * (costs.fee_bps + costs.slippage_bps)
                    draws = matched_null(
                        series_map,
                        episodes,
                        config.hold_bars,
                        round_trip,
                        seed=20260727,
                    )
                    observed = float(net.mean())
                    p = float((int((draws >= observed).sum()) + 1) / (NULL_DRAWS + 1))
                    entry["matched_null"] = {
                        "null_mean_bps": float(draws.mean()),
                        "null_p95_bps": float(np.quantile(draws, 0.95)),
                        "observed_bps": observed,
                        "excess_bps": observed - float(draws.mean()),
                        "p_value": p,
                        "search_family": SEARCH_FAMILY,
                        "sidak_p": sidak_correction(p, SEARCH_FAMILY),
                        "neighbour_family": FAMILY_TRIALS,
                    }
                    report["fingerprints"] = {
                        inst: runs[inst][1].manifest.primary_fingerprint for inst in LEGS
                    }
            tiers[tier] = entry
        report["versions"][version] = tiers

    return report


def gates(report: dict) -> dict:
    main = report["versions"]["main"]
    primary = main["main"]
    stress = main["stress"]
    yearly_returns = [y["return_pct"] for y in primary["yearly"].values()]
    positive_years = sum(1 for r in yearly_returns if r > 0)
    neighbours = [
        report["versions"][name]["main"]["total_return_pct"]
        for name in FROZEN_VERSIONS
        if name != "main"
    ]
    per_leg = primary["diagnostics"]["per_leg"]

    checks = {
        "main cost net > 0": primary["mean_net_bps"] > 0,
        "stress cost net > 0": stress["mean_net_bps"] > 0,
        f"positive years >= 4 (got {positive_years}/{len(yearly_returns)})": (
            positive_years >= min(4, len(yearly_returns))
        ),
        "return less best episode > 0": primary["mean_less_best_bps"] > 0,
        "cluster bootstrap P5 > 0": primary["cluster_bootstrap"]["p5"] > 0,
        "sidak p < 0.10": primary["matched_null"]["sidak_p"] < 0.10,
        f"neighbours profitable >= 4 (got {sum(1 for n in neighbours if n > 0)}/6)": (
            sum(1 for n in neighbours if n > 0) >= 4
        ),
        "max drawdown <= 25%": abs(primary["max_drawdown_pct"]) <= 25.0,
        "no gap-chased entries": primary["gap_chased_entries"] == 0,
        "both legs positive": all(
            v["net_bps"] is not None and v["net_bps"] > 0 for v in per_leg.values()
        ),
    }
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/cq.db")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default=FORWARD_FREEZE)
    parser.add_argument("--label", default="explore")
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="acknowledge and record a read past the explore boundary",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    start_ms, end_ms = to_ms(args.start), to_ms(args.end)
    if end_ms > to_ms(FORWARD_FREEZE) and not args.holdout:
        raise SystemExit(
            f"--end {args.end} reaches past the explore boundary {FORWARD_FREEZE}; "
            "pass --holdout to record the access"
        )

    # Record before reading, never after. A run that reads the holdout and then
    # dies before logging has still consumed it, and the log is the only thing
    # that makes the read correctable.
    if args.holdout:
        plan = forward_holdout("bic-majors-v1", end=args.end)
        record_holdout_access(
            study="bic-majors-v1",
            segment="forward",
            hypothesis=(
                "BIC-Majors v1, frozen at q99 / hold 12 / cooldown 12 / trailing 168, "
                "both legs at 0.25 weight on BTC-USDT-SWAP and ETH-USDT-SWAP, 7 bps "
                "per side plus 1 bp per funding crossing: impulse continuation earns "
                "a positive net return with cluster-bootstrap P5 > 0, at least 150 "
                "episodes, and both legs individually positive."
            ),
            fingerprint=plan.fingerprint,
        )

    with Store(args.db) as store:
        report = evaluate(store, start_ms, end_ms, args.label)

    report["gates"] = gates(report)
    report["verdict"] = "PASS" if all(report["gates"].values()) else "FAIL"
    if args.holdout:
        report["holdout_recorded"] = True
        report["holdout_reads_so_far"] = holdout_access_count("bic-majors-v1")

    out = Path(args.out or f"reports/research/bic_majors_{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))

    print(f"=== BIC-Majors v1 — {args.label} "
          f"({report['window']['start']} .. {report['window']['end']}) ===")
    print(f"bars: {report['bars']}")
    primary = report["versions"]["main"]["main"]
    print(f"\nmain @7bps: {primary['episodes']} episodes  "
          f"net {primary['mean_net_bps']:+.1f} bps  win {100*primary['win_rate']:.1f}%")
    print(f"  total {primary['total_return_pct']:+.2f}%  "
          f"MaxDD {primary['max_drawdown_pct']:.2f}%  Sharpe {primary['sharpe']:.2f}")
    mn = primary["matched_null"]
    print(f"  matched-random excess {mn['excess_bps']:+.1f} bps  "
          f"p={mn['p_value']:.4f}  Sidak(N={mn['search_family']}) p={mn['sidak_p']:.4f}")
    cb = primary["cluster_bootstrap"]
    print(f"  cluster bootstrap ({cb['clusters']} clusters) "
          f"P5 {cb['p5']:+.1f}  P50 {cb['p50']:+.1f}")
    print("\n  逐年:")
    for year, stats in primary["yearly"].items():
        print(f"    {year}: n={stats['episodes']:>3}  净 {stats['mean_net_bps']:+7.1f} bps  "
              f"收益 {stats['return_pct']:+7.2f}%  MaxDD {stats['max_drawdown_pct']:6.2f}%")

    print("\n  成本档:")
    for tier in COST_TIERS:
        t = report["versions"]["main"][tier]
        print(f"    {tier:<8} net {t['mean_net_bps']:+7.1f} bps  "
              f"total {t['total_return_pct']:+8.2f}%  MaxDD {t['max_drawdown_pct']:6.2f}%")

    print("\n  邻域 @7bps:")
    for name in FROZEN_VERSIONS:
        if name == "main":
            continue
        v = report["versions"][name]["main"]
        print(f"    {name:<9} n={v['episodes']:>4}  净 {v['mean_net_bps']:+7.1f} bps  "
              f"total {v['total_return_pct']:+8.2f}%")

    print("\n  机制诊断 (只报告, 不设门):")
    for key, value in primary["diagnostics"].items():
        if key == "per_leg":
            for inst, stats in value.items():
                shown = "—" if stats["net_bps"] is None else f"{stats['net_bps']:+.1f}"
                print(f"    {inst:<20} n={stats['n']:>4}  净 {shown} bps")
            continue
        shown = "—" if value["net_bps"] is None else f"{value['net_bps']:+.1f}"
        print(f"    {key:<20} n={value['n']:>4}  净 {shown} bps")

    print("\n  门:")
    for name, ok in report["gates"].items():
        print(f"    {'PASS' if ok else 'FAIL'} — {name}")
    print(f"\n  裁决: {report['verdict']}")
    print(f"  写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
