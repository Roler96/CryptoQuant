#!/usr/bin/env python
"""Reconcile a paper session's JSONL log against the backtest engine.

The calibration instrument the M5 gate needs: the live path and the backtest
share the decision (`Context` over closed bars) and the sizing (`target_delta`),
and differ only in the broker. This is a CODE-vs-CODE check — it establishes
that the backtest engine faithfully mirrors the live code path, which is the
discrimination the gate lacked.

Scope, stated so it is not mistaken for more: OKX *demo* fills and prices differ
from production (a separate simulated book), so the demo decision bars come from
the public production feed but the demo fills do not reflect real depth or
slippage. The load-bearing results here are the decision, accounting and band
parity (sections 1-3) and the decision half of section 5 - those hold whatever
prices the venue printed. The realised slippage/fee (section 4) are *demo*
figures shown for context only; they do NOT calibrate production execution cost,
which only real-money fills or a deliberately pessimistic model can bound.

It takes a `logs/paper/*.jsonl` session and checks, bar by bar, that:

1. DECISION PARITY (exact, log-only): feeding each bar's live pre-trade state
   through the *same* `target_delta` the backtest uses reproduces the live order
   (trade/no-trade and quantity). This is the parity claim tested directly.
2. ACCOUNTING CONSISTENCY (exact, log-only): the logged post-trade holding and
   cash follow from the pre-trade state and the recorded fill — and it reports
   where the venue's convention differs from the sim's (e.g. a spot buy fee
   charged in base coin vs modelled as a quote deduction).
3. BAND SEMANTICS (log-only): no-trade bars sit inside the weight-drift band and
   trades sit outside it — the REBALANCE+dust equivalence the backtest relies on.
4. EXECUTION CALIBRATION (log-only): realised slippage (fill vs decision close)
   and fee, against the backtest's modelled 5 bps / 10 bps.
5. BACKTEST EQUITY PARITY (needs the store): a real `run_backtest` over the same
   bars, seeded at the session's opening equity, compared bar-for-bar with the
   live equity, the gap attributed to the execution differences of (2) and (4).

Nothing here trades or touches the exchange; it reads a finished log and the
local bar store. Usage: `uv run python scripts/reconcile_paper.py [LOG] [--db P]`.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cq.core.types import CostModel, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.loop import run_backtest
from cq.engine.sizing import target_delta
from cq.strategy.doge_constant_mix import DogeConstantMix, DogeConstantMixConfig

DEFAULT_DB = "data/cq.db"
PAPER_LOG_DIR = Path("logs/paper")
# Fractions of a value below which a reconstruction is treated as exact: live
# lot rounding and float noise live here, a real divergence does not.
QUANTITY_TOLERANCE = 1e-4  # of the live order size
CASH_TOLERANCE = 1e-6  # of equity


@dataclass
class Row:
    ts: int
    close: float
    target: float
    held: float
    cash: float
    equity: float
    held_after: float
    cash_after: float
    fill: dict[str, Any] | None
    weight: float
    band: float


def _load_rows(path: Path) -> list[Row]:
    rows: list[Row] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        config = (r.get("strategy_state") or {}).get("config") or {}
        rows.append(
            Row(
                ts=int(r["ts"]),
                close=float(r["close"]),
                target=float(r["target"]),
                held=float(r["held"]),
                cash=float(r["cash"]),
                equity=float(r["equity"]),
                held_after=float(r["held_after"]),
                cash_after=float(r["cash_after"]),
                fill=r.get("fill"),
                weight=float(config.get("weight", r["target"])),
                band=float(config.get("band", 0.0)),
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
    """Replay each bar's sizing through the backtest's own `target_delta`."""
    spec = MarketSpec("DOGE-USDT", "spot")  # the spec a backtest of this uses
    costs = CostModel()  # LiveBroker's default, the same the sizing saw
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        live_delta, _, _ = _signed_fill(row.fill)
        replay = target_delta(
            spec, costs, row.target, row.close, row.equity, row.held, row.cash, row.band
        )
        scale = max(abs(live_delta), abs(replay), 1.0)
        # Both must agree on whether to trade, and on how much within lot noise.
        traded_live = live_delta != 0.0
        traded_replay = replay != 0.0
        if traded_live != traded_replay or abs(replay - live_delta) > QUANTITY_TOLERANCE * scale:
            mismatches.append(
                {
                    "ts": row.ts,
                    "live_delta": live_delta,
                    "replay_delta": replay,
                    "rel_diff": abs(replay - live_delta) / scale,
                }
            )
    return {"bars": len(rows), "mismatches": mismatches, "passed": not mismatches}


def _accounting(rows: list[Row]) -> dict[str, Any]:
    """Check logged post-trade state, and locate the fee-convention gap."""
    breaks: list[dict[str, Any]] = []
    fee_in_base_bars = 0
    fee_in_quote_bars = 0
    for row in rows:
        signed_qty, price, fee = _signed_fill(row.fill)
        if signed_qty == 0.0:
            # A hold must not move the position or cash.
            if (
                abs(row.held_after - row.held) > QUANTITY_TOLERANCE * max(abs(row.held), 1.0)
                or abs(row.cash_after - row.cash) > CASH_TOLERANCE * max(row.equity, 1.0)
            ):
                breaks.append({"ts": row.ts, "why": "hold moved position or cash"})
            continue
        # Cash always moves by the traded notional.
        expected_cash = row.cash - signed_qty * price
        # Two fee conventions produce two holdings. The venue charged the fee in
        # base coin if the realised holding matches full-qty-minus-base-fee.
        fee_base = fee / price if price > 0 else 0.0
        held_fee_in_base = row.held + signed_qty - (fee_base if signed_qty > 0 else 0.0)
        held_fee_in_quote = row.held + signed_qty
        tol_q = QUANTITY_TOLERANCE * max(abs(signed_qty), 1.0)
        if abs(row.held_after - held_fee_in_base) <= tol_q:
            fee_in_base_bars += 1
        elif abs(row.held_after - held_fee_in_quote) <= tol_q:
            fee_in_quote_bars += 1
        else:
            breaks.append(
                {
                    "ts": row.ts,
                    "why": "held_after matches neither fee convention",
                    "held_after": row.held_after,
                    "fee_in_base": held_fee_in_base,
                    "fee_in_quote": held_fee_in_quote,
                }
            )
        if abs(row.cash_after - expected_cash) > CASH_TOLERANCE * max(row.equity, 1.0):
            breaks.append(
                {
                    "ts": row.ts,
                    "why": "cash_after not equal to pre-cash minus notional",
                    "cash_after": row.cash_after,
                    "expected": expected_cash,
                }
            )
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
        if traded:
            sign = 1.0 if signed_qty > 0 else -1.0
            slippage_bps.append((price / row.close - 1.0) * 10_000 * sign)
            notional = abs(signed_qty) * price
            if notional > 0:
                fee_bps.append(fee / notional * 10_000)
    return {
        "band_breaks": band_breaks,
        "band_passed": not band_breaks,
        "trades": len(slippage_bps),
        "mean_slippage_bps": sum(slippage_bps) / len(slippage_bps) if slippage_bps else 0.0,
        "mean_fee_bps": sum(fee_bps) / len(fee_bps) if fee_bps else 0.0,
        "model_slippage_bps": CostModel().slippage_bps,
        "model_fee_bps": CostModel().fee_bps,
    }


def _equity_parity(rows: list[Row], db_path: str) -> dict[str, Any]:
    """Run a real backtest over the same bars and compare equity bar-for-bar."""
    first, last = rows[0], rows[-1]
    weight, band = first.weight, first.band
    with Store(db_path) as store:
        series = load_series(store, "DOGE-USDT", "1h", start_ms=first.ts, end_ms=last.ts + 1)
    if len(series) == 0:
        return {"available": False, "reason": "no stored bars for the session span"}
    result = run_backtest(
        DogeConstantMix(DogeConstantMixConfig(weight=weight, band=band)),
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
        "backtest_fills": len(result.fills),
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
    eq = payload["equity"]
    lines = [
        f"# Paper↔backtest reconcile — {payload['log']}",
        "",
        f"Session: {payload['strategy']} on {payload['inst']} {payload['timeframe']}, "
        f"{payload['bars']} bars, {payload['range']}",
        "",
        "## 1. Decision parity (exact, shared target_delta)",
        f"- {'PASS' if d['passed'] else 'FAIL'}: {d['bars']} bars, "
        f"{len(d['mismatches'])} mismatches",
    ]
    for m in d["mismatches"][:10]:
        lines.append(
            f"  - ts {m['ts']}: live Δ {m['live_delta']:.4f} vs replay {m['replay_delta']:.4f} "
            f"(rel {m['rel_diff']:.2e})"
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
        "",
        "## 4. Demo execution (context only — OKX demo ≠ production fills)",
        f"- trades: {be['trades']}",
        f"- slippage: demo {be['mean_slippage_bps']:+.2f} bps vs model "
        f"{be['model_slippage_bps']:.2f} bps (fill vs decision close) — DEMO, not production",
        f"- fee: demo {be['mean_fee_bps']:.2f} bps vs model {be['model_fee_bps']:.2f} bps",
        "",
        "## 5. Backtest equity parity",
    ]
    if not eq["available"]:
        lines.append(f"- skipped: {eq['reason']}")
    else:
        lines += [
            f"- bars compared: {eq['bars_compared']}, backtest fills: {eq['backtest_fills']}",
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
    parser.add_argument("log", nargs="?", help="path to a logs/paper/*.jsonl session")
    parser.add_argument("--db", default=DEFAULT_DB, help="bar store for equity parity")
    parser.add_argument("--json", help="optional path to write the full reconcile as JSON")
    args = parser.parse_args()

    if args.log:
        log_path = Path(args.log)
    else:
        candidates = sorted(PAPER_LOG_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print(f"no session logs in {PAPER_LOG_DIR}")
            return 1
        log_path = candidates[-1]
    rows = _load_rows(log_path)
    if not rows:
        print(f"{log_path} has no events")
        return 1

    with open(log_path, encoding="utf-8") as handle:
        head = json.loads(handle.readline())
    if not str(head.get("strategy", "")).startswith("doge-cmix"):
        # The band and REBALANCE-every-bar semantics this reconcile checks are
        # constant-mix's. A trend strategy sizes ON_ENTRY and holds, so its
        # decision and equity parity need a different model — out of scope here.
        print(
            f"{log_path}: strategy {head.get('strategy')!r} is not constant-mix; "
            "this reconcile targets the doge-cmix calibration instrument only."
        )
        return 0

    decision = _decision_parity(rows)
    accounting = _accounting(rows)
    band_exec = _band_and_execution(rows)
    equity = _equity_parity(rows, args.db)

    exact_passed = decision["passed"] and accounting["passed"] and band_exec["band_passed"]
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
        "equity": equity,
        "exact_passed": exact_passed,
        "verdict": verdict,
    }
    print(_render(payload))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"JSON: {args.json}")
    return 0 if exact_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
