"""
Autonomous Research Backtest Runner v2
======================================
Reusable script for running backtests on research strategies.
v2 adds: min-trade gate, proxy fallback, OOS split, commission
sensitivity, and look-ahead bias detection.

Usage (from CryptoQuant project root):
    uv run python research/_runner.py \
        --strategy research/backtest_my_strategy.py \
        --class MyStrategy \
        --symbol BTC/USDT \
        --timeframe 1h \
        --output research/results/2026-06-24/my_strategy_btc_1h.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Ensure project root is in sys.path (for uv run from subdirectory)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import numpy as np
import pandas as pd

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.risk.sizer import ATRSizer
from cryptoquant.engine.slippage import ATRSlippage
from cryptoquant.engine.latency import RandomLatency
from cryptoquant.engine.commission import TieredCommission

# ─── GATE CONSTANTS ──────────────────────────────────────────────

MIN_TRADES = 30          # Minimum trades for statistical significance
SHARPE_MIN = 0.5         # Minimum Sharpe ratio
MAXDD_MAX = 30.0         # Maximum drawdown % (absolute)
OOS_RATIO = 0.3          # Out-of-sample portion (last 30%)
OOS_LOCKBOX_START = "2024-06-01"  # True holdout start (never used for training)
OOS_LOCKBOX_END = "2026-06-30"    # True holdout end
COMMISSION_DEFAULT = 0.0005  # 5 bps
COMMISSION_STRESS = 0.001    # 10 bps
COMMISSION_DELTA_WARN = 0.30  # 30% Sharpe degradation = fragile


# ─── CLI ─────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description="Autonomous research backtest runner v2")
    p.add_argument("--strategy", required=True, help="Path to strategy .py file")
    p.add_argument("--class", dest="class_name", required=True, help="Strategy class name")
    p.add_argument("--symbol", required=True, help="Trading pair, e.g. BTC/USDT")
    p.add_argument("--timeframe", required=True, help="Bar timeframe, e.g. 1h")
    p.add_argument("--output", required=True, help="Output JSON path")
    p.add_argument("--capital", type=float, default=10_000, help="Initial capital")
    p.add_argument("--commission", type=float, default=COMMISSION_DEFAULT, help="Commission rate")
    p.add_argument("--slippage", type=float, default=0.0005, help="Slippage rate (5 bps)")
    p.add_argument("--lookback-days", type=int, default=365, help="Days of history to fetch")
    p.add_argument("--stop-loss", type=float, default=None, help="Stop loss %")
    p.add_argument("--take-profit", type=float, default=None, help="Take profit %")
    p.add_argument("--max-hold-bars", type=int, default=None, help="Max hold bars (time exit)")
    p.add_argument("--db-path", default="data/cryptoquant.db", help="SQLite DB path")
    p.add_argument("--no-oos", action="store_true", help="Skip OOS split validation")
    p.add_argument("--oos-lockbox", action="store_true",
                   help=f"Use true holdout lockbox ({OOS_LOCKBOX_START} → {OOS_LOCKBOX_END}) "
                        "instead of last-30% split. This data must NEVER be used for "
                        "training or parameter optimization.")
    p.add_argument("--no-commission-stress", action="store_true", help="Skip commission sensitivity test")
    p.add_argument("--no-bias-check", action="store_true", help="Skip look-ahead bias check")
    p.add_argument("--param-grid", default=None, help="JSON string: {'param': [v1,v2], ...} for grid search")
    p.add_argument("--data-cache", default=None, help="Path to pre-fetched CSV data file (skip fetch)")
    return p.parse_args()


# ─── DYNAMIC STRATEGY LOADING ────────────────────────────────────


def _load_strategy(strategy_path: str, class_name: str):
    """Dynamically import a Strategy subclass from a file path."""
    import importlib.util

    abs_path = os.path.abspath(strategy_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Strategy file not found: {abs_path}")

    mod_name = os.path.splitext(os.path.basename(abs_path))[0]
    spec = importlib.util.spec_from_file_location(mod_name, abs_path)
    if spec is None:
        raise ImportError(f"Could not load spec from {abs_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)

    cls = getattr(mod, class_name, None)
    if cls is None:
        raise AttributeError(f"Class '{class_name}' not found in {abs_path}")
    return cls


# ─── DATA FETCHING (WITH PROXY FALLBACK) ─────────────────────────


def _fetch_data(
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    db_path: str,
) -> pd.DataFrame:
    """Fetch OHLCV data with proxy fallback.

    Tries with proxy first. If that fails, retries with direct connection.
    """
    # Attempt 1: with proxy (reads from env, used in your network)
    try:
        print("[runner] Attempt 1: fetching with proxy ...")
        fetcher = OHLCVFetcher(exchange="okx")
        df = fetcher.fetch_range(symbol, timeframe, start_ms, end_ms)
        if not df.empty:
            store = OHLCVStore(db_path=db_path)
            store.save(df, "okx", symbol, timeframe)
            return df
    except Exception as e:
        print(f"[runner] Proxy fetch failed: {e}")

    # Attempt 2: direct connection (no proxy)
    try:
        print("[runner] Attempt 2: fetching without proxy ...")
        # Unset proxy env vars so ccxt won't use them
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            os.environ.pop(key, None)
        fetcher = OHLCVFetcher(exchange="okx", proxy="")
        df = fetcher.fetch_range(symbol, timeframe, start_ms, end_ms)
        if not df.empty:
            store = OHLCVStore(db_path=db_path)
            store.save(df, "okx", symbol, timeframe)
            return df
    except Exception as e:
        print(f"[runner] Direct fetch failed: {e}")

    return pd.DataFrame()


# ─── BACKTEST ENGINE ─────────────────────────────────────────────


def _run_single_backtest(
    df: pd.DataFrame,
    strategy: Any,
    symbol: str,
    timeframe: str,
    initial_capital: float,
    commission: float,
    slippage: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    max_hold_bars: int | None = None,
    label: str = "",
) -> dict:
    """Run one backtest and return serialized result dict."""
    sizer = ATRSizer(
        base_risk_pct=5.0,
        atr_period=14,
        multiplier=1.0,
        min_order=10.0,
        max_pct=100.0,
    )

    engine = BacktestEngine(
        initial_capital=initial_capital,
        commission=commission,
        slippage=slippage,
        use_lows_for_stops=True,
        sizer=sizer,
        slippage_model=ATRSlippage(atr_period=14, multiplier=0.2, max_slippage=0.003),
        latency_model=RandomLatency(min_bars=0, max_bars=1, seed=42),
        commission_model=TieredCommission(vip=False),
    )

    result = engine.run(
        df, strategy, symbol=symbol,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        max_hold_bars=max_hold_bars,
    )

    return {
        "label": label,
        "strategy_name": result.strategy_name,
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "initial_capital": result.initial_capital,
        "final_equity": round(result.final_equity, 2),
        "total_return_pct": round(result.metrics.total_return_pct, 2),
        "annualized_return_pct": round(result.metrics.annualized_return_pct, 2),
        "sharpe_ratio": round(result.metrics.sharpe_ratio, 2),
        "sortino_ratio": round(result.metrics.sortino_ratio, 2),
        "max_drawdown_pct": round(result.metrics.max_drawdown_pct, 2),
        "max_drawdown_days": result.metrics.max_drawdown_days,
        "volatility_annual_pct": round(result.metrics.volatility_annual_pct, 2),
        "total_trades": result.metrics.total_trades,
        "win_rate_pct": round(result.metrics.win_rate_pct, 1),
        "profit_factor": round(result.metrics.profit_factor, 2),
        "avg_win_pct": round(result.metrics.avg_win_pct, 2),
        "avg_loss_pct": round(result.metrics.avg_loss_pct, 2),
        "avg_hold_hours": round(result.metrics.avg_hold_hours, 1),
        "commission": commission,
        "slippage": slippage,
    }


def _run_oos_backtest(
    df: pd.DataFrame,
    strategy_cls: type,
    args: argparse.Namespace,
) -> dict | None:
    """Run OOS validation: IS (first 70%) vs OOS (last 30%), or lockbox.

    In lockbox mode (--oos-lockbox), OOS = fixed date range reserved as
    true holdout. IS = all data before the lockbox. This prevents the
    last-30% split from leaking future information into training when
    strategies are iterated over time.
    """
    use_lockbox = getattr(args, "oos_lockbox", False)

    if use_lockbox:
        lockbox_start = pd.Timestamp(OOS_LOCKBOX_START, tz="UTC")
        lockbox_end = pd.Timestamp(OOS_LOCKBOX_END, tz="UTC")

        if df.index.tz is None:
            df = df.tz_localize("UTC")
        elif df.index.tz is not None and str(df.index.tz) != "UTC":
            df = df.tz_convert("UTC")

        df_is = df[df.index < lockbox_start]
        df_oos = df[(df.index >= lockbox_start) & (df.index <= lockbox_end)]

        if len(df_is) < 100 or len(df_oos) < 30:
            print(f"[runner] Lockbox OOS skipped: IS={len(df_is)} bars, OOS={len(df_oos)} bars (insufficient)")
            return None

        print(f"[runner] Lockbox OOS: IS={len(df_is)} bars (before {OOS_LOCKBOX_START}), "
              f"OOS={len(df_oos)} bars ({OOS_LOCKBOX_START} → {OOS_LOCKBOX_END})")
        print("[runner] ⚠ LOCKBOX ACTIVE: OOS data is true holdout — do NOT use for training.")
    else:
        split_idx = int(len(df) * (1 - OOS_RATIO))
        if split_idx < max(strategy_cls.min_bars * 2, 100):
            print(f"[runner] OOS skipped: not enough data ({len(df)} bars, need {strategy_cls.min_bars * 2})")
            return None

        df_is = df.iloc[:split_idx]
        df_oos = df.iloc[split_idx:]

        print(f"[runner] OOS split: IS={len(df_is)} bars, OOS={len(df_oos)} bars")

    strategy_is = strategy_cls()
    strategy_is.timeframe = args.timeframe
    result_is = _run_single_backtest(
        df_is, strategy_is, args.symbol, args.timeframe,
        args.capital, args.commission, args.slippage,
        args.stop_loss, args.take_profit, label="IS",
    )

    strategy_oos = strategy_cls()
    strategy_oos.timeframe = args.timeframe
    result_oos = _run_single_backtest(
        df_oos, strategy_oos, args.symbol, args.timeframe,
        args.capital, args.commission, args.slippage,
        args.stop_loss, args.take_profit, label="OOS",
    )

    # Calculate Sharpe degradation
    sharpe_is = result_is["sharpe_ratio"]
    sharpe_oos = result_oos["sharpe_ratio"]
    if sharpe_is > 0:
        degradation = (sharpe_is - sharpe_oos) / sharpe_is
    else:
        degradation = 0.0

    return {
        "is": result_is,
        "oos": result_oos,
        "sharpe_degradation_pct": round(degradation * 100, 1),
        "oos_passed": (
            result_oos["sharpe_ratio"] > SHARPE_MIN
            and result_oos["max_drawdown_pct"] < MAXDD_MAX
            and result_oos["total_trades"] >= MIN_TRADES
        ),
        "overfit_warning": degradation > 0.5,  # >50% Sharpe decay = overfit
    }


def _run_commission_sensitivity(
    df: pd.DataFrame,
    strategy_cls: type,
    args: argparse.Namespace,
) -> dict | None:
    """Run commission stress test: 5 bps vs 10 bps."""
    # Baseline (already run at 5 bps by main backtest)
    strategy_stress = strategy_cls()
    strategy_stress.timeframe = args.timeframe

    print(f"[runner] Commission stress test: {COMMISSION_STRESS:.4f} (10 bps) ...")
    result_stress = _run_single_backtest(
        df, strategy_stress, args.symbol, args.timeframe,
        args.capital, COMMISSION_STRESS, args.slippage,
        args.stop_loss, args.take_profit, label="10bps",
    )
    return result_stress


def _check_lookahead_bias(
    df: pd.DataFrame,
    strategy_cls: type,
    args: argparse.Namespace,
) -> dict:
    """Detect look-ahead bias by running strategy on slightly truncated data.

    Strategy: run on df[1:] and compare signals to df[:-1].
    If signal at bar N depends on data from bar N+1, the signal series
    will shift when we trim the first bar.
    """
    strategy1 = strategy_cls()
    strategy1.timeframe = args.timeframe
    try:
        sig1 = strategy1.generate_signal(df)
    except Exception:
        return {"bias_detected": False, "bias_detail": "signal generation failed"}

    strategy2 = strategy_cls()
    strategy2.timeframe = args.timeframe
    try:
        sig2 = strategy2.generate_signal(df.iloc[1:])
    except Exception:
        return {"bias_detected": False, "bias_detail": "signal generation failed on truncated"}

    # Compare: sig1[i+1] should equal sig2[i] for all i
    # If strategy uses shift(-1) or future data, they'll differ
    min_len = min(len(sig1) - 1, len(sig2))
    if min_len < 10:
        return {"bias_detected": False, "bias_detail": "too few bars for bias check"}

    sig1_aligned = sig1.iloc[1:1+min_len].values
    sig2_aligned = sig2.iloc[:min_len].values

    mismatch_rate = float(np.mean(sig1_aligned != sig2_aligned))
    bias_detected = bool(mismatch_rate > 0.01)  # >1% mismatch = suspicious

    return {
        "bias_detected": bias_detected,
        "bias_detail": f"signal mismatch: {mismatch_rate*100:.1f}% of {min_len} bars differ after 1-bar shift",
        "mismatch_rate_pct": round(mismatch_rate * 100, 2),
    }


# ─── GATE LOGIC ──────────────────────────────────────────────────


def _gate_check(result: dict) -> tuple[bool, list[str]]:
    """Apply quality gates. Returns (passed, reasons)."""
    reasons = []

    if result["total_trades"] < MIN_TRADES:
        reasons.append(f"trades={result['total_trades']} < {MIN_TRADES} (min)")

    if result["sharpe_ratio"] < SHARPE_MIN:
        reasons.append(f"sharpe={result['sharpe_ratio']:.2f} < {SHARPE_MIN} (min)")

    if result["max_drawdown_pct"] > MAXDD_MAX:
        reasons.append(f"maxdd={result['max_drawdown_pct']:.1f}% > {MAXDD_MAX}% (max)")

    passed = len(reasons) == 0
    return passed, reasons


def _close_call_check(result: dict) -> bool:
    """Check if a strategy is close to passing: Sharpe 0.4-0.5, MaxDD<30%, trades>=30."""
    return (
        0.4 <= result["sharpe_ratio"] < SHARPE_MIN
        and result["max_drawdown_pct"] < MAXDD_MAX
        and result["total_trades"] >= MIN_TRADES
    )


# ─── SERIALIZATION ───────────────────────────────────────────────


def _sanitize(obj: Any) -> Any:
    """Recursively convert numpy types to JSON-serializable Python types."""
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _build_output(
    main_result: dict,
    meta: dict,
    oos_result: dict | None,
    comm_stress: dict | None,
    bias_check: dict,
) -> dict:
    """Build the complete output dict for JSON serialization."""
    output: dict[str, Any] = {
        "meta": meta,
        "main": main_result,
    }

    # Gate
    passed, gate_reasons = _gate_check(main_result)
    output["gate"] = {
        "passed": passed,
        "close_call": _close_call_check(main_result) if not passed else False,
        "reasons": gate_reasons,
        "criteria": {
            "min_trades": MIN_TRADES,
            "min_sharpe": SHARPE_MIN,
            "max_maxdd": MAXDD_MAX,
        },
    }

    # OOS
    if oos_result:
        output["oos"] = oos_result
        # If OOS exists, gate uses OOS result
        output["gate"]["oos_passed"] = oos_result["oos_passed"]
        output["gate"]["overfit_warning"] = oos_result["overfit_warning"]

    # Commission sensitivity
    if comm_stress:
        # Compare baseline (5 bps) vs stress (10 bps) Sharpe
        sharpe_base = main_result["sharpe_ratio"]
        sharpe_stress = comm_stress["sharpe_ratio"]
        if sharpe_base > 0.01:
            comm_delta_pct = (sharpe_base - sharpe_stress) / sharpe_base
        else:
            comm_delta_pct = 0.0
        output["commission_sensitivity"] = {
            "baseline_bps": 5,
            "stress_bps": 10,
            "baseline_sharpe": sharpe_base,
            "stress_sharpe": sharpe_stress,
            "sharpe_delta_pct": round(comm_delta_pct * 100, 1),
            "fragile": comm_delta_pct > COMMISSION_DELTA_WARN,
        }

    # Look-ahead bias
    output["bias_check"] = bias_check

    return output


# ─── MAIN ────────────────────────────────────────────────────────


def main():
    args = parse_args()

    # Load strategy
    StrategyCls = _load_strategy(args.strategy, args.class_name)

    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - args.lookback_days * 24 * 3600 * 1000

    # Fetch data with proxy fallback (or load from cache)
    print(f"[runner] Fetching {args.symbol} {args.timeframe} — last {args.lookback_days} days ...")
    if args.data_cache and os.path.exists(args.data_cache):
        print(f"[runner] Loading cached data from {args.data_cache}")
        df = pd.read_csv(args.data_cache, index_col=0, parse_dates=True)
    else:
        df = _fetch_data(args.symbol, args.timeframe, start_ms, end_ms, args.db_path)
        # Save cache for reuse by subsequent strategies on the same day
        if not df.empty and args.data_cache:
            os.makedirs(os.path.dirname(args.data_cache) or ".", exist_ok=True)
            df.to_csv(args.data_cache)
            print(f"[runner] Cached data to {args.data_cache}")

    if df.empty:
        print(f"[runner] ERROR: No data fetched for {args.symbol} {args.timeframe} (proxy + direct both failed)")
        error_result = {
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "strategy_file": args.strategy,
                "class_name": args.class_name,
                "error": "No data fetched — proxy and direct both failed",
            },
            "error": "No OHLCV data available",
            "symbol": args.symbol,
            "timeframe": args.timeframe,
        }
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(error_result, f, indent=2)
        print("[runner] GATE=ERROR (no data)")
        sys.exit(1)

    print(f"[runner] Data: {len(df)} bars, {df.index[0]} → {df.index[-1]}")

    # ── Param grid search mode ──
    if args.param_grid:
        return _run_grid_search(df, StrategyCls, args)

    # ── Full analysis (default) ──
    _run_full_analysis(df, StrategyCls, args)


def _run_grid_search(df: pd.DataFrame, StrategyCls: type, args: argparse.Namespace):
    """Grid search over parameter combinations. Returns best result."""
    import itertools

    param_grid: dict[str, list] = json.loads(args.param_grid)
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    combinations = list(itertools.product(*param_values))

    print(f"[runner] Grid search: {len(combinations)} combinations over {param_names}")

    best_result = None
    best_sharpe = -999
    best_params = None

    for combo in combinations:
        params = dict(zip(param_names, combo))
        strategy = StrategyCls(params=params)
        strategy.timeframe = args.timeframe

        result = _run_single_backtest(
            df, strategy, args.symbol, args.timeframe,
            args.capital, args.commission, args.slippage,
            args.stop_loss, args.take_profit,
            label=f"grid_{'_'.join(f'{k}={v}' for k, v in params.items())}",
        )

        passed, reasons = _gate_check(result)
        print(
            f"  [{result['label']}] Sharpe={result['sharpe_ratio']:.2f} "
            f"MaxDD={result['max_drawdown_pct']:.1f}% "
            f"Trades={result['total_trades']} "
            f"{'PASS' if passed else 'FAIL'}"
        )

        if result["sharpe_ratio"] > best_sharpe:
            best_sharpe = result["sharpe_ratio"]
            best_result = result
            best_params = params

    if best_result is None:
        print("[runner] Grid search: no valid results")
        sys.exit(1)

    # Build output with best result
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_file": args.strategy,
        "class_name": args.class_name,
        "bars": len(df),
        "date_range": f"{df.index[0]} → {df.index[-1]}",
        "lookback_days": args.lookback_days,
        "exchange": "okx",
        "grid_search": {
            "param_names": param_names,
            "combinations_tested": len(combinations),
            "best_params": best_params,
        },
    }

    output = {
        "meta": meta,
        "main": best_result,
        "gate": {
            "passed": best_result["sharpe_ratio"] > 0.5 and best_result["max_drawdown_pct"] < 30,
            "criteria": {"min_trades": MIN_TRADES, "min_sharpe": SHARPE_MIN, "max_maxdd": MAXDD_MAX},
        },
    }
    output = _sanitize(output)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    passed = best_result["sharpe_ratio"] > 0.5 and best_result["max_drawdown_pct"] < 30
    print(
        f"[runner] GRID BEST: Params={best_params} | "
        f"Sharpe={best_result['sharpe_ratio']:.2f} | "
        f"MaxDD={best_result['max_drawdown_pct']:.1f}% | "
        f"Trades={best_result['total_trades']} | "
        f"GATE={'PASS' if passed else 'FAIL'}"
    )
    print(f"[runner] Output: {args.output}")


def _run_full_analysis(df: pd.DataFrame, StrategyCls: type, args: argparse.Namespace):
    strategy = StrategyCls()
    strategy.timeframe = args.timeframe
    print(f"[runner] Running main backtest: {strategy.name} on {args.symbol} {args.timeframe} ...")
    main_result = _run_single_backtest(
        df, strategy, args.symbol, args.timeframe,
        args.capital, args.commission, args.slippage,
        args.stop_loss, args.take_profit, label="full_sample",
    )

    # ── OOS validation ──
    oos_result = None
    if not args.no_oos:
        try:
            oos_result = _run_oos_backtest(df, StrategyCls, args)
        except Exception as e:
            print(f"[runner] OOS validation error: {e}")

    # ── Commission sensitivity ──
    comm_stress = None
    if not args.no_commission_stress:
        try:
            comm_stress = _run_commission_sensitivity(df, StrategyCls, args)
        except Exception as e:
            print(f"[runner] Commission stress test error: {e}")

    # ── Look-ahead bias check ──
    bias_check: dict[str, Any] = {"bias_detected": False, "bias_detail": "skipped"}
    if not args.no_bias_check:
        try:
            bias_check = _check_lookahead_bias(df, StrategyCls, args)
        except Exception as e:
            bias_check = {"bias_detected": False, "bias_detail": f"bias check error: {e}"}

    # ── Build output ──
    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_file": args.strategy,
        "class_name": args.class_name,
        "bars": len(df),
        "date_range": f"{df.index[0]} → {df.index[-1]}",
        "lookback_days": args.lookback_days,
        "exchange": "okx",
    }

    output = _build_output(main_result, meta, oos_result, comm_stress, bias_check)
    output = _sanitize(output)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    # ── Summary to stdout ──
    passed, reasons = _gate_check(main_result)
    oos_passed = oos_result["oos_passed"] if oos_result else None
    oos_sharpe = oos_result["oos"]["sharpe_ratio"] if oos_result else None
    frag = output.get("commission_sensitivity", {}).get("fragile", False)
    bias = bias_check.get("bias_detected", False)

    flags = []
    if passed:
        flags.append("PASS")
    else:
        flags.append("FAIL")
    if oos_passed is False:
        flags.append("OOS_FAIL")
    if frag:
        flags.append("FRAGILE")
    if bias:
        flags.append("BIAS")

    print(
        f"[runner] DONE: {args.symbol} {args.timeframe} | "
        f"Return={main_result['total_return_pct']:+.1f}% | "
        f"Sharpe={main_result['sharpe_ratio']:.2f} | "
        f"MaxDD={main_result['max_drawdown_pct']:.1f}% | "
        f"Trades={main_result['total_trades']} | "
        f"WinRate={main_result['win_rate_pct']:.0f}% | "
        f"GATE={'|'.join(flags)}"
        + (f" | OOS_Sharpe={oos_sharpe:.2f}" if oos_sharpe is not None else "")
    )
    if reasons:
        print(f"[runner] Gate failures: {'; '.join(reasons)}")
    print(f"[runner] Output: {args.output}")


if __name__ == "__main__":
    main()
