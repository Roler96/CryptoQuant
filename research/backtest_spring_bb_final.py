"""
Spring Reversal — Final Validation: BB %B [0.12, 0.65)
======================================================
Detailed analysis of the best walk-forward configuration found in the BB %B sweep.
[0.12, 0.65) was the ONLY config with 6/7 WF profitable on OKX.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import sma, atr as atr_func, adx, rsi, bollinger_bands, pct_change_rolling
from backtest_spring_reversal import spring_signal, regime_backtest

def compute_metrics(trades):
    if not trades:
        return {"trades": 0, "sum": 0.0, "compound": 0.0, "sharpe": 0.0,
                "sortino": 0.0, "max_dd": 0.0, "win_rate": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "pf": 0.0, "max_consec": 0}
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    compound = 1.0
    for p in pnls:
        compound *= (1 + p / 100)
    compound_return = (compound - 1) * 100
    equity = [10000]
    for p in pnls:
        equity.append(equity[-1] * (1 + p / 100))
    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    max_dd = dd.min()
    max_consec = 0
    consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
    downside = [p for p in pnls if p < 0]
    sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if downside and len(pnls) > 1 and np.std(downside) > 0 else 0
    return {
        "trades": len(trades),
        "sum": sum(pnls),
        "compound": compound_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "win_rate": len(wins) / len(pnls) * 100 if pnls else 0,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "pf": sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0,
        "max_consec": max_consec,
    }

def walk_forward_analysis(df, signal_series, params, n_splits=7):
    n = len(df)
    slot = len(df) // (n_splits + 2)
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        split_sig = signal_series.iloc[start:end]
        t = regime_backtest(split_df, split_sig, {}, **params)
        if t:
            p = [x["pnl_pct"] for x in t]
            ss = sum(p)
            ssh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
        else:
            ss = 0
            ssh = 0
        results.append({
            "split": s + 1, "start": split_df.index[0], "end": split_df.index[-1],
            "trades": len(t) if t else 0, "sum": ss, "sharpe": ssh,
        })
    return results

def main():
    print("=" * 75)
    print("SPRING REVERSAL — FINAL: BB %B [0.12, 0.65)")
    print("=" * 75)

    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")

    base_exit_params = {
        "stop_pct": 3.0, "target_pct": 2.75, "max_hold": 32,
        "commission": 0.0005, "slippage": 0.0005,
    }

    # Prep OKX
    df = df_okx.copy()
    df["sma200"] = sma(df["close"], 200)
    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]
    base_sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)

    # =========================================================================
    # CONFIG: BB [0.12, 0.65) — best WF
    # =========================================================================
    sig_012_065 = base_sig & (df["close"] > df["sma200"]) & (df["bb_pct_b"] >= 0.12) & (df["bb_pct_b"] < 0.65)

    # Baseline [0.20, 0.60) for comparison
    sig_baseline = base_sig & (df["close"] > df["sma200"]) & (df["bb_pct_b"] >= 0.20) & (df["bb_pct_b"] < 0.60)

    print(f"\nSignals: baseline={sig_baseline.sum()}, expanded={sig_012_065.sum()}")

    # =========================================================================
    # FULL BACKTEST: [0.12, 0.65)
    # =========================================================================
    print("\n" + "=" * 75)
    print("FULL BACKTEST: BB %B [0.12, 0.65) — OKX BTC/USDT 1h")
    print("=" * 75)

    regime_data = {
        "bb_pct_b": df["bb_pct_b"].values,
    }
    trades = regime_backtest(df, sig_012_065, regime_data, **base_exit_params)
    m = compute_metrics(trades)

    print(f"\n  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"  BB %B Filter:       [0.12, 0.65)")
    print(f"  Exit:               s3.0/t2.75/h32")
    print(f"")
    print(f"  Total Trades:       {m['trades']}")
    print(f"  Compound Return:    {m['compound']:+.1f}%")
    print(f"  Linear Sum:         {m['sum']:+.1f}%")
    print(f"  Sharpe Ratio:       {m['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {m['sortino']:+.2f}")
    print(f"  Max Drawdown:       {m['max_dd']:+.1f}%")
    print(f"  Win Rate:           {m['win_rate']:.1f}%")
    print(f"  Avg Win:            {m['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {m['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {m['pf']:.2f}")
    print(f"  Max Consec Losses:  {m['max_consec']}")

    exit_counts = Counter(t["exit_reason"] for t in trades)
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in trades if t["exit_reason"] == reason]
        if subset:
            sp = [t["pnl_pct"] for t in subset]
            print(f"    {reason:15s}: {len(subset):4d} ({len(subset)/len(trades)*100:5.1f}%)  "
                  f"avg={np.mean(sp):+.2f}%  total={sum(sp):+.1f}%")

    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    print(f"\n  MFE: mean={np.mean(mfes):+.2f}%, median={np.median(mfes):+.2f}%, max={np.max(mfes):+.2f}%")
    print(f"  MAE: mean={np.mean(maes):+.2f}%, median={np.median(maes):+.2f}%")

    time_ex = [t for t in trades if t["exit_reason"] == "time_exit"]
    if time_ex:
        profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
        print(f"\n  Time-exit profitable at some point: {profitable_time}/{len(time_ex)} "
              f"({profitable_time/len(time_ex)*100:.1f}%)")

    # =========================================================================
    # WALK-FORWARD: [0.12, 0.65) — OKX
    # =========================================================================
    print("\n" + "=" * 75)
    print("WALK-FORWARD: BB %B [0.12, 0.65) — OKX (7 splits)")
    print("=" * 75)

    wf = walk_forward_analysis(df, sig_012_065, base_exit_params, n_splits=7)
    wf_pos = 0
    all_sh = []
    total_sum = 0
    for r in wf:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_pos += 1
        all_sh.append(r["sharpe"])
        total_sum += r["sum"]
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  "
              f"trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    print(f"  → {wf_pos}/7 profitable, mean OOS Sharpe: {np.mean(all_sh):+.2f}, total OOS: {total_sum:+.1f}%")

    # =========================================================================
    # REGIME ANALYSIS: [0.12, 0.65)
    # =========================================================================
    print("\n" + "=" * 75)
    print("REGIME ANALYSIS: BB %B [0.12, 0.65)")
    print("=" * 75)

    # Tag trades with BB %B at entry
    bb_at_entry = []
    for t in trades:
        if "bb_pct_b" in t:
            bb_at_entry.append(t["bb_pct_b"])

    if bb_at_entry:
        bb_at_entry = np.array(bb_at_entry, dtype=float)
        bb_at_entry = bb_at_entry[~np.isnan(bb_at_entry)]
        print(f"\n  BB %B at entry distribution:")
        print(f"    Min:    {np.min(bb_at_entry):.2f}")
        print(f"    25%:    {np.percentile(bb_at_entry, 25):.2f}")
        print(f"    50%:    {np.percentile(bb_at_entry, 50):.2f}")
        print(f"    75%:    {np.percentile(bb_at_entry, 75):.2f}")
        print(f"    Max:    {np.max(bb_at_entry):.2f}")

        # Performance by BB %B sub-range at entry
        print(f"\n  Performance by BB %B zone at entry:")
        print(f"  {'Zone':>15s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'Avg PnL':>8s}")
        print(f"  {'-'*60}")
        zones = [(0.12, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50), (0.50, 0.65)]
        for low, high in zones:
            subset = [t for t in trades if t.get("bb_pct_b") is not None 
                      and not np.isnan(t["bb_pct_b"]) 
                      and low <= t["bb_pct_b"] < high]
            if subset:
                p = [t["pnl_pct"] for t in subset]
                ss = sum(p)
                sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
                wr = sum(1 for x in p if x > 0) / len(p) * 100
                print(f"  [{low:.2f}, {high:.2f}){' '*6} {len(subset):>7d} {ss:>+7.1f}% {sh:>+7.2f} {wr:>5.1f}% {np.mean(p):>+7.2f}%")

    # =========================================================================
    # BASELINE COMPARISON
    # =========================================================================
    print("\n" + "=" * 75)
    print("BASELINE vs EXPANDED COMPARISON")
    print("=" * 75)

    base_trades = regime_backtest(df, sig_baseline, {}, **base_exit_params)
    b_m = compute_metrics(base_trades)

    print(f"\n  {'Metric':25s} {'Baseline [0.20,0.60)':>22s} {'Expanded [0.12,0.65)':>22s} {'Delta':>10s}")
    print(f"  {'-'*80}")
    comparisons = [
        ("Trades", b_m["trades"], m["trades"], lambda a, b: f"{b-a:+d} ({b/a*100-100:+.0f}%)"),
        ("Compound Return", b_m["compound"], m["compound"], lambda a, b: f"{b-a:+.1f}%"),
        ("Linear Sum", b_m["sum"], m["sum"], lambda a, b: f"{b-a:+.1f}%"),
        ("Sharpe", b_m["sharpe"], m["sharpe"], lambda a, b: f"{b-a:+.2f}"),
        ("Sortino", b_m["sortino"], m["sortino"], lambda a, b: f"{b-a:+.2f}"),
        ("Max Drawdown", b_m["max_dd"], m["max_dd"], lambda a, b: f"{b-a:+.1f}%"),
        ("Win Rate", b_m["win_rate"], m["win_rate"], lambda a, b: f"{b-a:+.1f}pp"),
        ("Avg Win", b_m["avg_win"], m["avg_win"], lambda a, b: f"{b-a:+.2f}%"),
        ("Avg Loss", b_m["avg_loss"], m["avg_loss"], lambda a, b: f"{b-a:+.2f}%"),
        ("Profit Factor", b_m["pf"], m["pf"], lambda a, b: f"{b-a:+.2f}"),
    ]
    for name, a, b, fmt in comparisons:
        if "Return" in name or "Drawdown" in name:
            a_str = f"{a:+.1f}%"
            b_str = f"{b:+.1f}%"
        elif name == "Trades":
            a_str = f"{a}"
            b_str = f"{b}"
        elif "Rate" in name:
            a_str = f"{a:.1f}%"
            b_str = f"{b:.1f}%"
        else:
            a_str = f"{a:+.2f}"
            b_str = f"{b:+.2f}"
        delta = fmt(a, b)
        print(f"  {name:25s} {a_str:>22s} {b_str:>22s} {delta:>10s}")

    # =========================================================================
    # BINANCE CROSS-VALIDATION
    # =========================================================================
    print("\n" + "=" * 75)
    print("BINANCE CROSS-VALIDATION: BB %B [0.12, 0.65)")
    print("=" * 75)

    df_b = df_binance.copy()
    df_b["sma200"] = sma(df_b["close"], 200)
    bb_b = bollinger_bands(df_b, 20, 2.0)
    df_b["bb_pct_b"] = bb_b["pct_b"]
    sig_b = spring_signal(df_b, lookback=20, vol_mult=1.5, close_pct=0.5)
    sig_b_exp = sig_b & (df_b["close"] > df_b["sma200"]) & (df_b["bb_pct_b"] >= 0.12) & (df_b["bb_pct_b"] < 0.65)
    sig_b_base = sig_b & (df_b["close"] > df_b["sma200"]) & (df_b["bb_pct_b"] >= 0.20) & (df_b["bb_pct_b"] < 0.60)

    # Expanded on Binance
    trades_be = regime_backtest(df_b, sig_b_exp, {}, **base_exit_params)
    if trades_be:
        m_be = compute_metrics(trades_be)
        print(f"\n  BB %B [0.12, 0.65) — Binance BTC/USDT 1h:")
        print(f"  Trades: {m_be['trades']}, Sum: {m_be['sum']:+.1f}%, Sharpe: {m_be['sharpe']:+.2f}, "
              f"WR: {m_be['win_rate']:.1f}%, PF: {m_be['pf']:.2f}, MaxDD: {m_be['max_dd']:+.1f}%")

        # Binance WF
        print(f"\n  Binance Walk-Forward (7 splits):")
        wf_be = walk_forward_analysis(df_b, sig_b_exp, base_exit_params, n_splits=7)
        wf_pos_be = 0
        all_sh_be = []
        total_sum_be = 0
        for r in wf_be:
            status = "✅" if r["sum"] > 0 else "❌"
            if r["sum"] > 0:
                wf_pos_be += 1
            all_sh_be.append(r["sharpe"])
            total_sum_be += r["sum"]
            print(f"    Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  "
                  f"trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
        print(f"    → {wf_pos_be}/7 profitable, mean OOS Sharpe: {np.mean(all_sh_be):+.2f}, total OOS: {total_sum_be:+.1f}%")

    # Baseline on Binance (for comparison)
    trades_bb = regime_backtest(df_b, sig_b_base, {}, **base_exit_params)
    if trades_bb:
        m_bb = compute_metrics(trades_bb)
        print(f"\n  BB %B [0.20, 0.60) (baseline) — Binance BTC/USDT 1h:")
        print(f"  Trades: {m_bb['trades']}, Sum: {m_bb['sum']:+.1f}%, Sharpe: {m_bb['sharpe']:+.2f}, "
              f"WR: {m_bb['win_rate']:.1f}%, PF: {m_bb['pf']:.2f}, MaxDD: {m_bb['max_dd']:+.1f}%")

        print(f"\n  {'Metric':25s} {'OKX [0.12,0.65)':>17s} {'Binance [0.12,0.65)':>19s} "
              f"{'Binance [0.20,0.60)':>19s}")
        print(f"  {'-'*82}")
        for name, a, b, c in [
            ("Trades", m["trades"], m_be["trades"], m_bb["trades"]),
            ("Sharpe", m["sharpe"], m_be["sharpe"], m_bb["sharpe"]),
            ("Return (sum)", m["sum"], m_be["sum"], m_bb["sum"]),
            ("Max DD", m["max_dd"], m_be["max_dd"], m_bb["max_dd"]),
            ("Win Rate", m["win_rate"], m_be["win_rate"], m_bb["win_rate"]),
            ("Profit Factor", m["pf"], m_be["pf"], m_bb["pf"]),
        ]:
            if name in ("Return (sum)", "Max DD"):
                print(f"  {name:25s} {a:>+16.1f}% {b:>+18.1f}% {c:>+18.1f}%")
            elif name == "Win Rate":
                print(f"  {name:25s} {a:>16.1f}% {b:>18.1f}% {c:>18.1f}%")
            elif name == "Trades":
                print(f"  {name:25s} {a:>17d} {b:>19d} {c:>19d}")
            else:
                print(f"  {name:25s} {a:>+17.2f} {b:>+19.2f} {c:>+19.2f}")

    # =========================================================================
    # YEARLY BREAKDOWN
    # =========================================================================
    print("\n" + "=" * 75)
    print("YEARLY PERFORMANCE: BB %B [0.12, 0.65) — OKX")
    print("=" * 75)

    yearly = {}
    for t in trades:
        year = df.index[t["entry_idx"]].year
        if year not in yearly:
            yearly[year] = []
        yearly[year].append(t["pnl_pct"])

    print(f"\n  {'Year':>6s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s}")
    print(f"  {'-'*40}")
    for year in sorted(yearly.keys()):
        p = yearly[year]
        ss = sum(p)
        sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
        wr = sum(1 for x in p if x > 0) / len(p) * 100
        print(f"  {year:>6d} {len(p):>7d} {ss:>+7.1f}% {sh:>+7.2f} {wr:>5.1f}%")

    print("\n" + "=" * 75)
    print("DONE")
    print("=" * 75)

if __name__ == "__main__":
    main()
