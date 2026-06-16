"""
Wick Inversion — Session-Based Pattern Analysis
================================================
Analysis: Does the vol-gated Wick strategy perform differently across trading sessions?

Tags every trade by UTC hour and session at entry, then:
1. Per-session performance breakdown
2. Per-hour-of-day performance heatmap
3. Session-filtered variants (only trade during best sessions)
4. Walk-forward validation of session filters

Strategy: Wick v4.5.0 — Vol Gate + s3.0/t2.5/h16
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from collections import Counter, defaultdict

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.signals import (
    sma, atr as atr_func, wick_imbalance, pct_change_rolling
)
from cryptoquant.strategy.base import Strategy


# ============================================================================
# Session utilities
# ============================================================================

def utc_hour_from_timestamp(ts):
    """Extract UTC hour from timestamp (ms or ns)."""
    # Timestamps can be in ms or ns
    if ts > 1e15:  # nanoseconds
        ts = ts // 1_000_000
    if ts > 1e12:  # milliseconds
        ts = ts // 1000
    return (ts // 3600) % 24


def classify_session(hour):
    """Classify UTC hour into trading session."""
    if 0 <= hour < 8:
        return "asian"       # Tokyo, HK, Singapore
    elif 8 <= hour < 13:
        return "london"      # London morning
    elif 13 <= hour < 16:
        return "london_ny"   # Overlap (London afternoon + NY morning)
    elif 16 <= hour < 21:
        return "ny"          # NY afternoon
    else:
        return "off"         # 21-23 UTC: late NY / early Asian fringe


def classify_day_of_week(ts):
    """Classify timestamp into day of week (0=Mon, 6=Sun)."""
    if ts > 1e15:
        ts = ts // 1_000_000
    if ts > 1e12:
        ts = ts // 1000
    return pd.Timestamp(ts, unit='s').dayofweek


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ============================================================================
# Wick Vol Gate strategy (v4.5.0: optimized exits)
# ============================================================================

class WickVolGateOpt(Strategy):
    """Wick + vol gate with v4.5.0 optimized exits: s3.0/t2.5/h16"""
    timeframe = "1h"
    min_bars = 300
    version = "vol_gate_opt"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.25,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "hold_hours": 16,
    }

    @property
    def name(self) -> str:
        return "Wick_VolGate_Opt"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr
        signal = signal & (vol_ratio > 1.0)

        return signal.astype(int)


# ============================================================================
# Session-filtered variant
# ============================================================================

class WickVolGateOptSessions(Strategy):
    """Wick + vol gate (opt exits) + session filter"""
    timeframe = "1h"
    min_bars = 300
    version = "vol_gate_opt_sessions"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.25,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "hold_hours": 16,
        "allowed_sessions": ["asian", "london", "london_ny", "ny", "off"],  # all by default
    }

    @property
    def name(self) -> str:
        return "Wick_VolGate_Opt_Sessions"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr
        signal = signal & (vol_ratio > 1.0)

        # Session filter: only trade during allowed sessions
        if self.params.get("allowed_sessions"):
            hours = pd.Series(df.index).apply(
                lambda ts: utc_hour_from_timestamp(getattr(ts, 'value', ts))
            )
            sessions = hours.apply(classify_session)
            allowed = sessions.isin(self.params["allowed_sessions"])
            signal = signal & allowed.values

        return signal.astype(int)


# ============================================================================
# Walk-Forward
# ============================================================================

def walk_forward(df, strategy_cls, n_splits=6, label="", strategy_kwargs=None):
    """Walk-forward validation."""
    if strategy_kwargs is None:
        strategy_kwargs = {}
    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()

        if len(split_df) < 300:
            continue

        strategy = strategy_cls(**strategy_kwargs)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            split_df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params["stop_pct"],
            take_profit_pct=strategy.params["target_pct"],
            max_hold_bars=strategy.params["hold_hours"],
        )

        trades = result.trades
        lin_sum = sum(t.pnl_pct for t in trades)
        sharpe = result.metrics.sharpe_ratio

        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")

        results.append({
            "split": s + 1,
            "period": f"{start_date}->{end_date}",
            "trades": len(trades),
            "sum": lin_sum,
            "sharpe": sharpe,
        })

    return results


def print_wf_table(results, label):
    """Print walk-forward results."""
    print(f"\n--- {label} ---")
    print(f"{'Split':>5s}  {'Period':20s}  {'Trades':>6s}  {'Sum':>8s}  {'Sharpe':>7s}  {'Status':>6s}")
    print("-" * 65)
    for r in results:
        status = "OK" if r["sum"] > 0 else "FAIL"
        print(f"  {r['split']:>3d}  {r['period']:20s}  {r['trades']:>6d}  {r['sum']:>+7.1f}%  {r['sharpe']:>+7.2f}  {status:>6s}")

    profitable = sum(1 for r in results if r["sum"] > 0)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"\n  -> {profitable}/{len(results)} OOS profitable")
    print(f"  -> Mean OOS Sharpe: {mean_sharpe:+.2f}")
    print(f"  -> Total OOS Sum: {total_sum:+.1f}%")
    return profitable, mean_sharpe


def print_backtest_result(result, label):
    """Print backtest result summary."""
    m = result.metrics
    trades = result.trades

    exit_counts = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    exit_pnls = {}
    for t in trades:
        if t.exit_reason not in exit_pnls:
            exit_pnls[t.exit_reason] = []
        exit_pnls[t.exit_reason].append(t.pnl_pct)

    max_consec = 0
    current = 0
    for t in trades:
        if t.pnl_pct <= 0:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total Trades:       {len(trades)}")
    print(f"  Total Return:       {m.total_return_pct:+.1f}%")
    print(f"  Linear Sum:         {sum(t.pnl_pct for t in trades):+.1f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:.1f}%")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.3f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.3f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Max Consec Losses:  {max_consec}")

    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        count = exit_counts.get(reason, 0)
        pnl_list = exit_pnls.get(reason, [0])
        avg_pnl = np.mean(pnl_list) if pnl_list else 0
        total_pnl = sum(pnl_list)
        pct = count / len(trades) * 100 if trades else 0
        print(f"    {reason:15s} {count:>4d} ({pct:>4.1f}%)  avg={avg_pnl:>+7.3f}%  total={total_pnl:>+8.1f}%")

    return {
        "label": label,
        "trades": len(trades),
        "compound": m.total_return_pct,
        "linear_sum": sum(t.pnl_pct for t in trades),
        "annualized": m.annualized_return_pct,
        "sharpe": m.sharpe_ratio,
        "sortino": m.sortino_ratio,
        "max_dd": m.max_drawdown_pct,
        "win_rate": m.win_rate_pct,
        "avg_win": m.avg_win_pct,
        "avg_loss": m.avg_loss_pct,
        "profit_factor": m.profit_factor,
        "max_consec": max_consec,
    }


# ============================================================================
# Session analysis
# ============================================================================

def analyze_sessions(trades, df):
    """Tag each trade by session and analyze per-session performance."""
    session_trades = defaultdict(list)
    hour_trades = defaultdict(list)
    dow_trades = defaultdict(list)

    for t in trades:
        # Entry timestamp from trade
        entry_ts = t.entry_time

        # Get the bar index to extract session info
        entry_hour = utc_hour_from_timestamp(entry_ts)
        session = classify_session(entry_hour)
        dow = classify_day_of_week(entry_ts)

        session_trades[session].append(t)
        hour_trades[entry_hour].append(t)
        dow_trades[dow].append(t)

    return session_trades, hour_trades, dow_trades


def print_session_analysis(session_trades, hour_trades, dow_trades, total_trades):
    """Print detailed session analysis."""
    # Session analysis
    print(f"\n{'='*70}")
    print(f"  SESSION PERFORMANCE ANALYSIS")
    print(f"{'='*70}")

    print(f"\n{'Session':15s} {'Trades':>6s} {'%Total':>7s} {'Sum':>8s} {'Avg':>7s} {'Win%':>6s} {'PF':>6s} {'TP%':>6s} {'SL%':>6s}")
    print("-" * 78)

    session_order = ["asian", "london", "london_ny", "ny", "off"]
    session_stats = {}

    for sess in session_order:
        trades = session_trades.get(sess, [])
        if not trades:
            continue
        pnls = [t.pnl_pct for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        tp_count = sum(1 for t in trades if t.exit_reason == "take_profit")
        sl_count = sum(1 for t in trades if t.exit_reason == "stop_loss")

        sum_pnl = sum(pnls)
        avg_pnl = np.mean(pnls)
        win_rate = len(wins) / len(pnls) * 100
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float('inf')

        print(f"{sess:15s} {len(trades):>6d} {len(trades)/total_trades*100:>6.1f}% {sum_pnl:>+7.1f}% {avg_pnl:>+6.3f}% {win_rate:>5.1f}% {pf:>5.2f} {tp_count/len(trades)*100:>5.1f}% {sl_count/len(trades)*100:>5.1f}%")

        session_stats[sess] = {
            "trades": len(trades),
            "sum": sum_pnl,
            "avg": avg_pnl,
            "win_rate": win_rate,
            "pf": pf,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "tp_pct": tp_count / len(trades) * 100,
            "sl_pct": sl_count / len(trades) * 100,
        }

    # Hourly heatmap (text-based)
    print(f"\n{'='*70}")
    print(f"  HOURLY PERFORMANCE (UTC)")
    print(f"{'='*70}")
    print(f"\n{'Hour':>5s} {'Session':12s} {'Trades':>6s} {'Sum':>8s} {'Avg':>7s} {'Win%':>6s}")
    print("-" * 52)

    hour_stats = {}
    for hour in range(24):
        trades = hour_trades.get(hour, [])
        if not trades:
            continue
        pnls = [t.pnl_pct for t in trades]
        wins = [p for p in pnls if p > 0]
        sum_pnl = sum(pnls)
        avg_pnl = np.mean(pnls)
        win_rate = len(wins) / len(pnls) * 100

        session = classify_session(hour)
        bar = "+" * max(1, int(avg_pnl * 100)) if avg_pnl > 0 else "-" * max(1, int(abs(avg_pnl) * 100))

        print(f"  {hour:>3d}h  {session:12s} {len(trades):>6d} {sum_pnl:>+7.1f}% {avg_pnl:>+6.3f}% {win_rate:>5.1f}%  {bar}")

        hour_stats[hour] = {
            "trades": len(trades),
            "sum": sum_pnl,
            "avg": avg_pnl,
            "win_rate": win_rate,
        }

    # Day of week analysis
    print(f"\n{'='*70}")
    print(f"  DAY-OF-WEEK PERFORMANCE")
    print(f"{'='*70}")
    print(f"\n{'Day':>5s} {'Trades':>6s} {'%Total':>7s} {'Sum':>8s} {'Avg':>7s} {'Win%':>6s}")
    print("-" * 46)

    dow_stats = {}
    for dow in range(7):
        trades = dow_trades.get(dow, [])
        if not trades:
            continue
        pnls = [t.pnl_pct for t in trades]
        wins = [p for p in pnls if p > 0]
        sum_pnl = sum(pnls)
        avg_pnl = np.mean(pnls)
        win_rate = len(wins) / len(pnls) * 100

        print(f"  {DAY_NAMES[dow]:>5s} {len(trades):>6d} {len(trades)/total_trades*100:>6.1f}% {sum_pnl:>+7.1f}% {avg_pnl:>+6.3f}% {win_rate:>5.1f}%")

        dow_stats[dow] = {
            "trades": len(trades),
            "sum": sum_pnl,
            "avg": avg_pnl,
            "win_rate": win_rate,
        }

    return session_stats, hour_stats, dow_stats


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("  WICK INVERSION — SESSION-BASED PATTERN ANALYSIS")
    print("  Vol Gate v4.5.0: s3.0/t2.5/h16")
    print("  OKX BTC/USDT 1h, 2019-2026, commission=5bps, slippage=5bps")
    print("=" * 70)

    # Load data
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nData: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")

    # ============================================================
    # PART 1: Run baseline (vol gate, no session filter)
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"  PART 1: BASELINE — Vol Gate v4.5.0 (no session filter)")
    print(f"{'#'*70}")

    strategy = WickVolGateOpt()
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    result = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=strategy.params["stop_pct"],
        take_profit_pct=strategy.params["target_pct"],
        max_hold_bars=strategy.params["hold_hours"],
    )
    baseline_stats = print_backtest_result(result, "Baseline: Vol Gate Opt (s3.0/t2.5/h16)")

    # Session analysis
    session_trades, hour_trades, dow_trades = analyze_sessions(result.trades, df)
    session_stats, hour_stats, dow_stats = print_session_analysis(
        session_trades, hour_trades, dow_trades, len(result.trades)
    )

    # Walk-forward baseline
    print(f"\n{'#'*70}")
    print(f"  WALK-FORWARD: Baseline")
    print(f"{'#'*70}")
    wf_baseline = walk_forward(df, WickVolGateOpt, n_splits=6, label="Baseline Vol Gate Opt")
    b_profitable, b_mean_sharpe = print_wf_table(wf_baseline, "WF: Baseline Vol Gate Opt")

    # ============================================================
    # PART 2: Identify best and worst sessions
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"  PART 2: SESSION RANKING")
    print(f"{'#'*70}")

    # Rank sessions by total sum
    ranked = sorted(session_stats.items(), key=lambda x: x[1]["sum"], reverse=True)
    print(f"\n  Session ranking by total PnL sum:")
    for rank, (sess, stats) in enumerate(ranked, 1):
        print(f"    {rank}. {sess:12s}  trades={stats['trades']:>4d}  sum={stats['sum']:>+7.1f}%  avg={stats['avg']:>+6.3f}%  wr={stats['win_rate']:>5.1f}%  pf={stats['pf']:>5.2f}")

    # Identify best combo: top N sessions
    best_sessions = [sess for sess, stats in ranked if stats["sum"] > 0]
    worst_sessions = [sess for sess, stats in ranked if stats["sum"] <= 0]
    print(f"\n  Profitable sessions: {best_sessions}")
    print(f"  Unprofitable sessions: {worst_sessions}")

    # ============================================================
    # PART 3: Test session-filtered variants
    # ============================================================

    # We need to be smart about which sessions to filter.
    # Don't filter if the session is mixing profitable years with unprofitable ones.
    # Instead, test removing clearly toxic sessions.

    # Build session combinations to test
    session_combos = []

    # Combo 1: Remove the worst session
    if worst_sessions:
        combo1 = [s for s in ["asian", "london", "london_ny", "ny", "off"] if s not in worst_sessions[:1]]
        session_combos.append((f"Remove worst: {worst_sessions[:1]}", combo1))

    # Combo 2: Keep only top 2 sessions
    top2 = [sess for sess, _ in ranked[:2]]
    session_combos.append((f"Keep top 2: {top2}", top2))

    # Combo 3: Keep only top 3 sessions
    top3 = [sess for sess, _ in ranked[:3]]
    session_combos.append((f"Keep top 3: {top3}", top3))

    # Combo 4: Remove all unprofitable sessions
    if len(best_sessions) < 5:
        session_combos.append((f"Keep only profitable: {best_sessions}", best_sessions))

    # Combo 5: Asian + London only (traditional high-vol sessions for BTC)
    session_combos.append(("Asian+London only", ["asian", "london", "london_ny"]))

    print(f"\n{'#'*70}")
    print(f"  PART 3: SESSION-FILTERED VARIANTS")
    print(f"{'#'*70}")

    all_variant_results = []

    for combo_label, allowed_sessions in session_combos:
        print(f"\n{'-'*60}")
        print(f"  Testing: {combo_label}")
        print(f"  Allowed sessions: {allowed_sessions}")
        print(f"{'-'*60}")

        strategy = WickVolGateOptSessions()
        strategy.params["allowed_sessions"] = allowed_sessions

        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params["stop_pct"],
            take_profit_pct=strategy.params["target_pct"],
            max_hold_bars=strategy.params["hold_hours"],
        )
        stats = print_backtest_result(result, combo_label)
        stats["label"] = combo_label
        all_variant_results.append(stats)

        # Walk-forward with session filter
        # Build a strategy factory for walk-forward
        def make_session_strategy():
            s = WickVolGateOptSessions()
            s.params["allowed_sessions"] = allowed_sessions
            return s

        class SessionFilteredWrapped(WickVolGateOpt):
            """Wrapper that applies session filter."""
            def generate_signal(self, df):
                df = self.preprocess(df)
                imb = wick_imbalance(df, window=self.params["imbalance_window"])
                price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
                signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

                atr14 = atr_func(df, 14)
                median_atr = atr14.rolling(200).median()
                vol_ratio = atr14 / median_atr
                signal = signal & (vol_ratio > 1.0)

                hours = pd.Series(df.index).apply(
                    lambda ts: utc_hour_from_timestamp(getattr(ts, 'value', ts))
                )
                sessions = hours.apply(classify_session)
                allowed = sessions.isin(allowed_sessions)
                signal = signal & allowed.values

                return signal.astype(int)

        wf_results = walk_forward(df, SessionFilteredWrapped, n_splits=6,
                                  label=f"WF: {combo_label}")
        print_wf_table(wf_results, f"WF: {combo_label}")

    # ============================================================
    # PART 4: Day-of-week filter
    # ============================================================
    print(f"\n{'#'*70}")
    print(f"  PART 4: DAY-OF-WEEK FILTER")
    print(f"{'#'*70}")

    # Test removing worst day(s)
    ranked_dow = sorted(dow_stats.items(), key=lambda x: x[1]["sum"], reverse=True)
    print(f"\n  Day-of-week ranking by total PnL sum:")
    for rank, (dow, stats) in enumerate(ranked_dow, 1):
        print(f"    {rank}. {DAY_NAMES[dow]:>5s}  trades={stats['trades']:>4d}  sum={stats['sum']:>+7.1f}%  avg={stats['avg']:>+6.3f}%  wr={stats['win_rate']:>5.1f}%")

    # Test: skip worst day
    worst_day = ranked_dow[-1][0] if ranked_dow else None
    if worst_day is not None:
        print(f"\n  Testing: Skip {DAY_NAMES[worst_day]}")

        class DowFiltered(WickVolGateOpt):
            def generate_signal(self, df):
                df = self.preprocess(df)
                imb = wick_imbalance(df, window=self.params["imbalance_window"])
                price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
                signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

                atr14 = atr_func(df, 14)
                median_atr = atr14.rolling(200).median()
                vol_ratio = atr14 / median_atr
                signal = signal & (vol_ratio > 1.0)

                # Skip worst day of week
                dows = pd.Series(df.index).apply(
                    lambda ts: classify_day_of_week(getattr(ts, 'value', ts))
                )
                signal = signal & (dows.values != worst_day)

                return signal.astype(int)

        strategy = DowFiltered()
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params["stop_pct"],
            take_profit_pct=strategy.params["target_pct"],
            max_hold_bars=strategy.params["hold_hours"],
        )
        stats = print_backtest_result(result, f"Skip {DAY_NAMES[worst_day]}")
        all_variant_results.append(stats)

    # ============================================================
    # PART 5: Summary comparison
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  FINAL COMPARISON")
    print(f"{'='*70}")
    print(f"{'Config':40s} {'Trades':>6s} {'Compound':>9s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 90)

    all_rows = [baseline_stats] + all_variant_results
    for r in all_rows:
        label = r.get("label", r.get("allowed_sessions", "unknown"))
        if isinstance(label, list):
            label = ",".join(label)
        print(f"{str(label):40s} {r['trades']:>6d} {r['compound']:>+8.1f}% {r['sharpe']:>+7.2f} {r['max_dd']:>6.1f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f}")

    print(f"\n{'='*70}")
    print(f"  RESEARCH COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
