#!/usr/bin/env python
"""Reconcile a paper session's JSONL log against the backtest engine.

The calibration instrument the M5 gate needs: the live path and the backtest
share `run_event_loop`, causal `Context` scheduling and `target_delta`; their
feed and broker implementations differ. This is a CODE-vs-CODE check of those
boundaries — it establishes that the simulated broker faithfully mirrors the
observable live behavior covered by this protocol.

Scope, stated so it is not mistaken for more: OKX *demo* fills and prices differ
from production (a separate simulated book), so the demo decision bars come from
the public production feed but the demo fills do not reflect real depth or
slippage. The load-bearing results here are the decision, accounting, band and
coverage checks (sections 1-4), plus completeness of the backtest comparison.
The realised slippage/fee (section 5) are *demo* figures shown for context only;
they do NOT calibrate production execution cost, which only real-money fills or
a deliberately pessimistic model can bound.

It takes a `logs/paper/*.jsonl` session and checks, bar by bar, that:

1. DECISION PARITY (exact, log-only): feeding each bar's live pre-trade state
   through both the shared `target_delta` and a separate calibration formula
   reproduces the live order (trade/no-trade and quantity).
2. ACCOUNTING CONSISTENCY (exact, log-only): the logged post-trade holding and
   cash follow from the pre-trade state and the recorded fill — and it reports
   where the venue's convention differs from the sim's (e.g. a spot buy fee
   charged in base coin vs modelled as a quote deduction).
3. BAND SEMANTICS (log-only): no-trade bars sit inside the weight-drift band and
   trades sit outside it — the REBALANCE+dust equivalence the backtest relies on.
4. EVENT COVERAGE (log-only): the frozen minimum bars, buy/sell transitions,
   inside-band holds, outside-band trades and rejection count.
5. DEMO EXECUTION CONTEXT (log-only): realised demo slippage and fee, explicitly
   not treated as production calibration.
6. BACKTEST EQUITY PARITY: a real `run_backtest` over the exact OHLCV bars
   frozen into the session log, seeded at the session's opening equity and
   compared bar-for-bar with the live equity.

Nothing here trades or touches the exchange; it reads a finished log. A log
path and a fixed holdout end are mandatory; there is no ``latest`` mode. Usage:

```
uv run python scripts/reconcile_paper.py LOG --holdout-end YYYY-MM-DD
```
"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from cq.calibration import (
    build_gate_artifact,
    file_sha256,
    write_gate_artifact,
)
from cq.context import Context, Series, series_fingerprint
from cq.core.clock import duration_ms
from cq.core.types import CostModel, Intent, MarketSpec, Side, Sizing
from cq.engine.loop import run_backtest
from cq.engine.sizing import target_delta
from cq.live.calibration_probe import (
    CALIBRATION_BAND,
    CALIBRATION_TARGETS,
    SpotCalibrationSequence,
)
from cq.research.split import ProtocolError, forward_holdout, record_holdout_access

CALIBRATION_STUDY = "ENGINE_CALIBRATION_SPOT_V1"
CALIBRATION_HYPOTHESIS = (
    "the named deterministic spot/rebalance session satisfies every exact parity and "
    "event-coverage check in engine calibration protocol v2026-07-24.2"
)
MIN_BARS = 200
MIN_POST_INITIAL_FILLS = 20
MIN_POST_INITIAL_BUYS = 5
MIN_POST_INITIAL_SELLS = 5
# Fractions of a value below which a reconstruction is treated as exact: live
# lot rounding and float noise live here, a real divergence does not.
QUANTITY_TOLERANCE = 1e-4  # of the live order size
CASH_TOLERANCE = 1e-6  # of equity


@dataclass
class Row:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    target: float
    held: float
    cash: float
    equity: float
    held_after: float
    cash_after: float
    fill: dict[str, Any] | None
    weight: float
    band: float
    rejected: int
    account_events: tuple[dict[str, Any], ...]
    strategy_state: dict[str, Any] | None
    has_full_ohlcv: bool


def _load_rows(path: Path) -> list[Row]:
    rows: list[Row] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        strategy_state = r.get("strategy_state")
        config = (strategy_state or {}).get("config") or {}
        close = float(r["close"])
        rows.append(
            Row(
                ts=int(r["ts"]),
                open=float(r.get("open", close)),
                high=float(r.get("high", close)),
                low=float(r.get("low", close)),
                close=close,
                volume=float(r.get("volume", 0.0)),
                target=float(r["target"]),
                held=float(r["held"]),
                cash=float(r["cash"]),
                equity=float(r["equity"]),
                held_after=float(r["held_after"]),
                cash_after=float(r["cash_after"]),
                fill=r.get("fill"),
                weight=float(config.get("weight", r["target"])),
                band=float(config.get("band", 0.0)),
                rejected=int(r.get("rejected", 0)),
                account_events=tuple(r.get("account_events") or ()),
                strategy_state=strategy_state,
                has_full_ohlcv=all(
                    field in r for field in ("open", "high", "low", "close", "volume")
                ),
            )
        )
    return rows


def _signed_fill(fill: dict[str, Any] | None) -> tuple[float, float, float]:
    """(signed quantity, price, fee) of a fill, or zeros when there was none."""
    if fill is None:
        return 0.0, 0.0, 0.0
    sign = 1.0 if fill["side"] == "buy" else -1.0
    return sign * float(fill["quantity"]), float(fill["price"]), float(fill["fee"])


def _decision_parity(rows: list[Row]) -> dict[str, Any]:
    """Replay sizing through both the shared code and an independent formula."""
    spec = MarketSpec("DOGE-USDT", "spot")  # the spec a backtest of this uses
    costs = CostModel()  # LiveBroker's default, the same the sizing saw
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        live_delta, _, _ = _signed_fill(row.fill)
        shared_replay = target_delta(
            spec, costs, row.target, row.close, row.equity, row.held, row.cash, row.band
        )
        independent_replay = _independent_target_delta(spec, costs, row)
        for source, replay in (
            ("shared_target_delta", shared_replay),
            ("independent_formula", independent_replay),
        ):
            scale = max(abs(live_delta), abs(replay), 1.0)
            traded_live = live_delta != 0.0
            traded_replay = replay != 0.0
            if (
                traded_live != traded_replay
                or abs(replay - live_delta) > QUANTITY_TOLERANCE * scale
            ):
                mismatches.append(
                    {
                        "ts": row.ts,
                        "source": source,
                        "live_delta": live_delta,
                        "replay_delta": replay,
                        "rel_diff": abs(replay - live_delta) / scale,
                    }
                )
    return {"bars": len(rows), "mismatches": mismatches, "passed": not mismatches}


def _independent_target_delta(
    spec: MarketSpec, costs: CostModel, row: Row
) -> float:
    """Calibration-only sizing formula, intentionally not delegated to the engine."""
    desired = spec.round_quantity(row.target * row.equity / row.close)
    delta = desired - row.held
    if delta > 0:
        slipped = costs.fill_price(row.close, Side.BUY)
        unit_cost = slipped * (1 + costs.fee_bps / 10_000)
        affordable = spec.round_quantity(max(row.cash, 0.0) / unit_cost)
        delta = min(delta, affordable)
    if abs(delta) * row.close < row.band * abs(row.equity):
        return 0.0
    return delta


def _accounting(rows: list[Row]) -> dict[str, Any]:
    """Check logged post-trade state, and locate the fee-convention gap."""
    breaks: list[dict[str, Any]] = []
    fee_in_base_bars = 0
    fee_in_quote_bars = 0
    previous: Row | None = None
    for row in rows:
        tolerance_cash = CASH_TOLERANCE * max(row.equity, 1.0)
        marked_equity = row.cash + row.held * row.close
        if abs(row.equity - marked_equity) > tolerance_cash:
            breaks.append(
                {
                    "ts": row.ts,
                    "why": "pre-trade equity is not cash plus marked holding",
                    "equity": row.equity,
                    "marked": marked_equity,
                }
            )
        if row.account_events:
            breaks.append(
                {
                    "ts": row.ts,
                    "why": "spot calibration row contains external account events",
                }
            )
        if previous is not None:
            held_tol = QUANTITY_TOLERANCE * max(abs(row.held), 1.0)
            if (
                abs(row.held - previous.held_after) > held_tol
                or abs(row.cash - previous.cash_after) > tolerance_cash
            ):
                breaks.append(
                    {
                        "ts": row.ts,
                        "why": "pre-trade state does not continue the previous post-trade state",
                    }
                )

        signed_qty, price, fee = _signed_fill(row.fill)
        if signed_qty == 0.0:
            # A hold must not move the position or cash.
            if (
                abs(row.held_after - row.held) > QUANTITY_TOLERANCE * max(abs(row.held), 1.0)
                or abs(row.cash_after - row.cash) > CASH_TOLERANCE * max(row.equity, 1.0)
            ):
                breaks.append({"ts": row.ts, "why": "hold moved position or cash"})
            previous = row
            continue

        # Match the complete post-trade state against the two explicit fee
        # conventions. `Fill.fee` is normalized to quote currency, so a base fee
        # corresponds to fee/price units.
        fee_base = fee / price if price > 0 else 0.0
        held_fee_in_base = row.held + signed_qty - fee_base
        cash_fee_in_base = row.cash - signed_qty * price
        held_fee_in_quote = row.held + signed_qty
        cash_fee_in_quote = row.cash - signed_qty * price - fee
        tol_q = QUANTITY_TOLERANCE * max(abs(signed_qty), 1.0)
        if (
            abs(row.held_after - held_fee_in_base) <= tol_q
            and abs(row.cash_after - cash_fee_in_base) <= tolerance_cash
        ):
            fee_in_base_bars += 1
        elif (
            abs(row.held_after - held_fee_in_quote) <= tol_q
            and abs(row.cash_after - cash_fee_in_quote) <= tolerance_cash
        ):
            fee_in_quote_bars += 1
        else:
            breaks.append(
                {
                    "ts": row.ts,
                    "why": "post-trade state matches neither fee convention",
                    "held_after": row.held_after,
                    "cash_after": row.cash_after,
                }
            )
        previous = row
    return {
        "breaks": breaks,
        "passed": not breaks,
        "fee_in_base_bars": fee_in_base_bars,
        "fee_in_quote_bars": fee_in_quote_bars,
    }


def _band_and_execution(rows: list[Row]) -> dict[str, Any]:
    """Weight-drift band behaviour and realised execution cost vs the model."""
    band_breaks: list[dict[str, Any]] = []
    slippage_bps: list[float] = []
    fee_bps: list[float] = []
    holds_inside_band = 0
    post_initial_trades_outside_band = 0
    seen_initial_trade = False
    for row in rows:
        signed_qty, price, fee = _signed_fill(row.fill)
        current_weight = row.held * row.close / row.equity if row.equity > 0 else 0.0
        drift = abs(row.target - current_weight)
        traded = signed_qty != 0.0
        # Sized delta notional is |target-current|*equity to first order, so the
        # band gate and the weight drift should agree on which side of `band` we
        # are — bar the first entry from flat, which is a full-weight buy.
        if not traded and drift > row.band + QUANTITY_TOLERANCE:
            band_breaks.append(
                {"ts": row.ts, "drift": drift, "band": row.band, "why": "held past band"}
            )
        elif not traded:
            holds_inside_band += 1
        if traded:
            if seen_initial_trade:
                if drift + QUANTITY_TOLERANCE < row.band:
                    band_breaks.append(
                        {
                            "ts": row.ts,
                            "drift": drift,
                            "band": row.band,
                            "why": "traded inside band",
                        }
                    )
                else:
                    post_initial_trades_outside_band += 1
            else:
                seen_initial_trade = True
            sign = 1.0 if signed_qty > 0 else -1.0
            slippage_bps.append((price / row.close - 1.0) * 10_000 * sign)
            notional = abs(signed_qty) * price
            if notional > 0:
                fee_bps.append(fee / notional * 10_000)
    return {
        "band_breaks": band_breaks,
        "band_passed": not band_breaks,
        "holds_inside_band": holds_inside_band,
        "post_initial_trades_outside_band": post_initial_trades_outside_band,
        "trades": len(slippage_bps),
        "mean_slippage_bps": sum(slippage_bps) / len(slippage_bps) if slippage_bps else 0.0,
        "mean_fee_bps": sum(fee_bps) / len(fee_bps) if fee_bps else 0.0,
        "model_slippage_bps": CostModel().slippage_bps,
        "model_fee_bps": CostModel().fee_bps,
    }


def _coverage(
    rows: list[Row], timeframe: str, band_exec: dict[str, Any]
) -> dict[str, Any]:
    trade_rows = [row for row in rows if _signed_fill(row.fill)[0] != 0.0]
    post_initial = trade_rows[1:]
    buys = sum(_signed_fill(row.fill)[0] > 0 for row in post_initial)
    sells = sum(_signed_fill(row.fill)[0] < 0 for row in post_initial)
    step = duration_ms(timeframe)
    consecutive = all(
        later.ts - earlier.ts == step for earlier, later in itertools.pairwise(rows)
    )
    rejected = sum(row.rejected for row in rows)
    checks = {
        "minimum_bars": len(rows) >= MIN_BARS,
        "consecutive_bars": consecutive,
        "minimum_post_initial_fills": len(post_initial) >= MIN_POST_INITIAL_FILLS,
        "minimum_post_initial_buys": buys >= MIN_POST_INITIAL_BUYS,
        "minimum_post_initial_sells": sells >= MIN_POST_INITIAL_SELLS,
        "hold_inside_band_observed": band_exec["holds_inside_band"] > 0,
        "trade_outside_band_observed": (
            band_exec["post_initial_trades_outside_band"] > 0
        ),
        "no_rejected_orders": rejected == 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "bars": len(rows),
        "post_initial_fills": len(post_initial),
        "post_initial_buys": buys,
        "post_initial_sells": sells,
        "rejected_orders": rejected,
    }


def _frozen_sequence(rows: list[Row], strategy_name: str) -> dict[str, Any]:
    probe = SpotCalibrationSequence()
    expected_config = probe.snapshot_state()["config"]
    checks = {
        "strategy_name": strategy_name == probe.name,
        "band": all(abs(row.band - CALIBRATION_BAND) <= 1e-12 for row in rows),
        "targets": all(
            row.target == CALIBRATION_TARGETS[index % len(CALIBRATION_TARGETS)]
            for index, row in enumerate(rows)
        ),
        "checkpoint_phase": all(
            row.strategy_state is not None
            and row.strategy_state.get("count") == index + 1
            and row.strategy_state.get("config") == expected_config
            for index, row in enumerate(rows)
        ),
        "full_ohlcv": all(
            row.has_full_ohlcv
            and row.high >= max(row.open, row.close)
            and row.low <= min(row.open, row.close)
            and row.volume > 0
            for row in rows
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


class _LoggedTargets:
    """Replay the exact frozen targets whose live executions are in the log."""

    name = "logged-spot-calibration-targets"
    warmup_bars = 1

    def __init__(self, targets: list[float]):
        self.targets = targets

    def reset(self) -> None:
        return None

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=self.targets[ctx.index], reason=self.name)


def _equity_parity(rows: list[Row], timeframe: str) -> dict[str, Any]:
    """Run a real backtest over the same bars and compare equity bar-for-bar."""
    first = rows[0]
    band = first.band
    if not all(row.has_full_ohlcv for row in rows):
        return {"available": False, "reason": "session log does not contain full OHLCV"}
    series = Series(
        "DOGE-USDT",
        timeframe,
        np.array([row.ts for row in rows], dtype=np.int64),
        np.array([row.open for row in rows], dtype=float),
        np.array([row.high for row in rows], dtype=float),
        np.array([row.low for row in rows], dtype=float),
        np.array([row.close for row in rows], dtype=float),
        np.array([row.volume for row in rows], dtype=float),
    )
    result = run_backtest(
        _LoggedTargets([row.target for row in rows]),
        series,
        MarketSpec("DOGE-USDT", "spot"),
        initial_cash=first.equity,
        costs=CostModel(),
        sizing=Sizing.REBALANCE,
        dust_fraction=band,
    )
    bt_equity = {int(ts): eq for ts, eq in zip(result.timestamps, result.equity, strict=True)}
    diffs: list[dict[str, Any]] = []
    max_rel = 0.0
    for row in rows:
        if row.ts not in bt_equity:
            continue
        bt = bt_equity[row.ts]
        rel = abs(bt - row.equity) / max(row.equity, 1.0)
        max_rel = max(max_rel, rel)
        diffs.append({"ts": row.ts, "live": row.equity, "backtest": bt, "rel_diff": rel})
    return {
        "available": True,
        "bars_compared": len(diffs),
        "complete": len(diffs) == len(rows),
        "backtest_fills": len(result.fills),
        "bar_series_fingerprint": series_fingerprint(series),
        "max_rel_equity_diff": max_rel,
        "final_live": diffs[-1]["live"] if diffs else None,
        "final_backtest": diffs[-1]["backtest"] if diffs else None,
        "series": diffs,
    }


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def _render(payload: dict[str, Any]) -> str:
    d = payload["decision"]
    a = payload["accounting"]
    be = payload["band_exec"]
    coverage = payload["coverage"]
    frozen = payload["frozen_sequence"]
    eq = payload["equity"]
    lines = [
        f"# Paper↔backtest reconcile — {payload['log']}",
        "",
        f"Session: {payload['strategy']} on {payload['inst']} {payload['timeframe']}, "
        f"{payload['bars']} bars, {payload['range']}",
        "",
        "## 0. Frozen calibration sequence",
        f"- {'PASS' if frozen['passed'] else 'FAIL'}: "
        + ", ".join(
            f"{name}={'PASS' if passed else 'FAIL'}"
            for name, passed in frozen["checks"].items()
        ),
        "",
        "## 1. Decision parity (exact, shared + independent sizing)",
        f"- {'PASS' if d['passed'] else 'FAIL'}: {d['bars']} bars, "
        f"{len(d['mismatches'])} mismatches",
    ]
    for m in d["mismatches"][:10]:
        lines.append(
            f"  - ts {m['ts']}: live Δ {m['live_delta']:.4f} vs replay {m['replay_delta']:.4f} "
            f"(rel {m['rel_diff']:.2e}, {m['source']})"
        )
    lines += [
        "",
        "## 2. Accounting consistency + fee convention",
        f"- {'PASS' if a['passed'] else 'FAIL'}: {len(a['breaks'])} breaks",
        f"- fee charged in BASE coin on {a['fee_in_base_bars']} trade bars, "
        f"in QUOTE on {a['fee_in_quote_bars']} — the sim models a quote deduction, so a "
        f"base-fee venue leaves the backtest holding slightly more coin and less cash "
        f"at equal equity.",
    ]
    for b in a["breaks"][:10]:
        lines.append(f"  - ts {b['ts']}: {b['why']}")
    lines += [
        "",
        "## 3. Band semantics",
        f"- {'PASS' if be['band_passed'] else 'FAIL'}: "
        f"{len(be['band_breaks'])} bars held past the band",
        f"- inside-band holds: {be['holds_inside_band']}; "
        f"post-initial outside-band trades: {be['post_initial_trades_outside_band']}",
        "",
        "## 4. Frozen event coverage",
        f"- {'PASS' if coverage['passed'] else 'FAIL'}: "
        f"{coverage['bars']} bars, {coverage['post_initial_fills']} post-initial fills "
        f"({coverage['post_initial_buys']} buys, {coverage['post_initial_sells']} sells)",
        "",
        "## 5. Demo execution (context only — OKX demo ≠ production fills)",
        f"- trades: {be['trades']}",
        f"- slippage: demo {be['mean_slippage_bps']:+.2f} bps vs model "
        f"{be['model_slippage_bps']:.2f} bps (fill vs decision close) — DEMO, not production",
        f"- fee: demo {be['mean_fee_bps']:.2f} bps vs model {be['model_fee_bps']:.2f} bps",
        "",
        "## 6. Backtest equity parity",
    ]
    if not eq["available"]:
        lines.append(f"- skipped: {eq['reason']}")
    else:
        lines += [
            f"- bars compared: {eq['bars_compared']} "
            f"({'complete' if eq['complete'] else 'PARTIAL'}), "
            f"backtest fills: {eq['backtest_fills']}",
            f"- live final equity {_fmt(eq['final_live'])} vs backtest "
            f"{_fmt(eq['final_backtest'])}",
            f"- max per-bar relative equity difference: {eq['max_rel_equity_diff']:.4%}",
        ]
    lines += [
        "",
        "## Verdict",
        f"**{payload['verdict']}**",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile a paper session log vs the backtest")
    parser.add_argument("log", help="explicit path to one frozen paper JSONL session")
    parser.add_argument(
        "--holdout-end",
        required=True,
        help="fixed exclusive YYYY-MM-DD end recorded before reading the session",
    )
    parser.add_argument(
        "--audit-path",
        default="reports/holdout_access.jsonl",
        help="holdout access audit log",
    )
    parser.add_argument("--json", help="optional path to write the full reconcile as JSON")
    parser.add_argument(
        "--artifact",
        help="optional calibration artifact path; writes PASS or FAILED fail-closed",
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.is_file():
        print(f"session log does not exist: {log_path}")
        return 1

    try:
        split = forward_holdout(CALIBRATION_STUDY, end=args.holdout_end)
    except ProtocolError as exc:
        print(f"invalid holdout boundary: {exc}")
        return 1
    record_holdout_access(
        CALIBRATION_STUDY,
        "forward",
        f"{CALIBRATION_HYPOTHESIS}; source={log_path.as_posix()}",
        split.fingerprint,
        args.audit_path,
    )

    rows = _load_rows(log_path)
    if not rows:
        print(f"{log_path} has no events")
        return 1
    segment = split.segment("forward")
    outside = [row.ts for row in rows if not segment.contains(row.ts)]
    if outside:
        print(
            f"{log_path}: {len(outside)} rows fall outside recorded holdout "
            f"{segment.start}..{segment.end}"
        )
        return 2

    with open(log_path, encoding="utf-8") as handle:
        head = json.loads(handle.readline())
    strategy_name = str(head.get("strategy", ""))
    if not (
        strategy_name.startswith("doge-cmix")
        or strategy_name == SpotCalibrationSequence().name
    ):
        print(
            f"{log_path}: strategy {strategy_name!r} is not a supported "
            "spot/rebalance calibration instrument."
        )
        return 2
    if head.get("inst_id") != "DOGE-USDT" or head.get("timeframe") != "5m":
        print(
            f"{log_path}: expected DOGE-USDT spot 5m, got "
            f"{head.get('inst_id')} {head.get('timeframe')}"
        )
        return 2

    decision = _decision_parity(rows)
    accounting = _accounting(rows)
    band_exec = _band_and_execution(rows)
    coverage = _coverage(rows, head["timeframe"], band_exec)
    frozen = _frozen_sequence(rows, strategy_name)
    equity = _equity_parity(rows, head["timeframe"])

    checks = {
        "frozen_calibration_sequence": frozen["passed"],
        "decision_parity": decision["passed"],
        "accounting_consistency": accounting["passed"],
        "band_semantics": band_exec["band_passed"],
        "event_coverage": coverage["passed"],
        "backtest_available": equity["available"],
        "backtest_complete": bool(equity.get("complete", False)),
    }
    exact_passed = all(checks.values())
    verdict = (
        "RECONCILED (code parity): decisions, accounting and band semantics match; "
        "residual equity gap is demo-fill execution, not a production cost calibration"
        if exact_passed
        else "DIVERGENCE: see failed sections above"
    )
    first = rows[0]
    payload: dict[str, Any] = {
        "log": str(log_path),
        "strategy": head["strategy"],
        "inst": head["inst_id"],
        "timeframe": head["timeframe"],
        "bars": len(rows),
        "range": f"{rows[0].ts}..{rows[-1].ts}",
        "weight": first.weight,
        "band": first.band,
        "decision": decision,
        "accounting": accounting,
        "band_exec": band_exec,
        "coverage": coverage,
        "frozen_sequence": frozen,
        "equity": equity,
        "exact_passed": exact_passed,
        "verdict": verdict,
    }
    print(_render(payload))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"JSON: {args.json}")
    if args.artifact:
        evidence = {
            "log": str(log_path),
            "bars": len(rows),
            "post_initial_fills": coverage["post_initial_fills"],
            "post_initial_buys": coverage["post_initial_buys"],
            "post_initial_sells": coverage["post_initial_sells"],
            "coverage_checks": coverage["checks"],
            "frozen_sequence_checks": frozen["checks"],
            "decision_mismatches": len(decision["mismatches"]),
            "accounting_breaks": len(accounting["breaks"]),
            "band_breaks": len(band_exec["band_breaks"]),
            "backtest_bars_compared": equity.get("bars_compared", 0),
            "bar_series_fingerprint": equity.get("bar_series_fingerprint"),
            "max_model_vs_demo_equity_diff": equity.get("max_rel_equity_diff"),
            "range_start_ms": rows[0].ts,
            "range_end_ms": rows[-1].ts,
            "holdout_fingerprint": split.fingerprint,
        }
        artifact = build_gate_artifact(
            "spot",
            "rebalance",
            checks=checks,
            evidence=evidence,
            source_sha256=file_sha256(log_path),
        )
        written = write_gate_artifact(artifact, args.artifact)
        print(f"Calibration artifact ({artifact['status']}): {written}")
    return 0 if exact_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
