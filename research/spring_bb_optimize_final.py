"""Spring v1.3.0: BB [0.15, 0.60) — full backtest + walk-forward + Binance cross-val."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from collections import Counter

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from strategies.spring import SpringReversal


def run_backtest(df, symbol, params):
    strategy = SpringReversal(params=params)
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=0.0005,
        slippage=0.0005,
        use_lows_for_stops=True,
    )
    return engine.run(
        df, strategy,
        symbol=symbol,
        stop_loss_pct=params["stop_pct"],
        take_profit_pct=params["target_pct"],
        max_hold_bars=params["hold_hours"],
    )


def walk_forward(df, params, n_splits=7):
    """7-split walk-forward validation."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []
    
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        
        try:
            result = run_backtest(split_df, "BTC/USDT", params)
            results.append({
                "split": s + 1,
                "start": split_df.index[0],
                "end": split_df.index[-1],
                "trades": result.metrics.total_trades,
                "return": result.metrics.total_return_pct,
                "sharpe": result.metrics.sharpe_ratio,
                "max_dd": result.metrics.max_drawdown_pct,
            })
        except Exception as e:
            results.append({
                "split": s + 1,
                "start": split_df.index[0],
                "end": split_df.index[-1],
                "trades": 0,
                "return": 0,
                "sharpe": 0,
                "max_dd": 0,
                "error": str(e),
            })
    
    return results


def main():
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    
    # Best config from BB sweep
    best_params = {
        "lookback": 20,
        "vol_mult": 1.5,
        "close_pct": 0.5,
        "stop_pct": 3.0,
        "target_pct": 2.75,
        "hold_hours": 32,
        "commission": 0.0005,
        "sma200_filter": True,
        "bb_filter": True,
        "bb_period": 20,
        "bb_std": 2.0,
        "bb_low": 0.15,
        "bb_high": 0.60,
    }
    
    # Baseline (v1.2.0)
    baseline_params = dict(best_params, bb_low=0.12, bb_high=0.65)
    
    print("=" * 70)
    print("SPRING REVERSAL — BB [0.15, 0.60) OPTIMIZATION")
    print("=" * 70)
    
    for label, params in [("Best (BB [0.15,0.60))", best_params), 
                           ("Baseline (BB [0.12,0.65))", baseline_params)]:
        print(f"\n{'='*70}")
        print(f"CONFIG: {label}")
        print(f"{'='*70}")
        
        for exchange, df in [("OKX", df_okx), ("Binance", df_binance)]:
            print(f"\n--- {exchange} ---")
            
            result = run_backtest(df, "BTC/USDT", params)
            m = result.metrics
            trades = result.trades
            
            if not trades:
                print("  NO TRADES")
                continue
            
            # Metrics
            pnls = [t.pnl_pct for t in trades]
            per_trade_sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
            
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            max_consec = 0
            consec = 0
            for p in pnls:
                if p <= 0:
                    consec += 1
                    max_consec = max(max_consec, consec)
                else:
                    consec = 0
            
            years = (df.index[-1] - df.index[0]).days / 365.25
            annualized = ((1 + m.total_return_pct/100) ** (1/years) - 1) * 100 if years > 0 else 0
            
            print(f"  Initial Capital:    10,000 USDT")
            print(f"  Commission:         5 bps (round-trip)")
            print(f"  Slippage:           5 bps")
            print(f"")
            print(f"  Total Trades:       {m.total_trades}")
            print(f"  Total Return:       {m.total_return_pct:+.2f}%")
            print(f"  Annualized Return:  {annualized:+.2f}%")
            print(f"  Sharpe Ratio:       {m.sharpe_ratio:.2f}")
            print(f"  Sortino Ratio:      {m.sortino_ratio:.2f}")
            print(f"  Max Drawdown:       {m.max_drawdown_pct:.2f}%")
            print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
            print(f"  Avg Win:            {m.avg_win_pct:+.2f}%")
            print(f"  Avg Loss:           {m.avg_loss_pct:+.2f}%")
            print(f"  Profit Factor:      {m.profit_factor:.2f}")
            print(f"  Max Consec Losses:  {max_consec}")
            print(f"  Per-Trade Sharpe:   {per_trade_sharpe:+.2f}")
            
            # Exit breakdown
            exit_counts = Counter(t.exit_reason for t in trades)
            print(f"\n  Exit Breakdown:")
            for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
                subset = [t for t in trades if t.exit_reason == reason]
                if subset:
                    sp = [t.pnl_pct for t in subset]
                    pct = len(subset) / len(trades) * 100
                    print(f"    {reason:15s}: {len(subset):4d} ({pct:5.1f}%)  avg={np.mean(sp):+.2f}%  total={sum(sp):+.1f}%")
            
            # MFE
            mfes = [t.mfe_pct for t in trades]
            print(f"\n  MFE: mean={np.mean(mfes):+.2f}%  median={np.median(mfes):+.2f}%  max={np.max(mfes):+.2f}%")
            
            time_ex = [t for t in trades if t.exit_reason == "time_exit"]
            if time_ex:
                profitable = sum(1 for t in time_ex if t.mfe_pct > 0)
                print(f"  Time-exits profitable: {profitable}/{len(time_ex)} ({profitable/len(time_ex)*100:.1f}%)")
            
            # Walk-forward
            wf = walk_forward(df, params)
            wf_positive = sum(1 for r in wf if r["return"] > 0)
            wf_sharpes = [r["sharpe"] for r in wf]
            
            print(f"\n  Walk-Forward (7 splits, OOS):")
            for r in wf:
                status = "✅" if r["return"] > 0 else "❌"
                print(f"    Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  "
                      f"trades={r['trades']:3d}  return={r['return']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
            print(f"    OOS Profitable: {wf_positive}/{len(wf)} splits")
            print(f"    Mean OOS Sharpe: {np.mean(wf_sharpes):+.2f}")
            print(f"    Total OOS Sum: {sum(r['return'] for r in wf):+.1f}%")
    
    # ========================================================================
    # COMPARISON
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"COMPARISON: Baseline vs Optimized")
    print(f"{'='*70}")
    
    for exchange in ["OKX", "Binance"]:
        df = df_okx if exchange == "OKX" else df_binance
        print(f"\n--- {exchange} ---")
        print(f"  {'Metric':20s} {'Baseline [0.12,0.65)':>22s} {'Best [0.15,0.60)':>22s} {'Delta':>12s}")
        print(f"  {'-'*78}")
        
        for config_label, config_params in [("Baseline", baseline_params), ("Best", best_params)]:
            result = run_backtest(df, "BTC/USDT", config_params)
            if config_label == "Baseline":
                base = result
            else:
                best = result
        
        metrics_to_compare = [
            ("Trades", "total_trades", "{:.0f}", False),
            ("Total Return", "total_return_pct", "{:+.2f}%", False),
            ("Sharpe", "sharpe_ratio", "{:.2f}", False),
            ("Max DD", "max_drawdown_pct", "{:.2f}%", True),
            ("Win Rate", "win_rate_pct", "{:.1f}%", False),
            ("Profit Factor", "profit_factor", "{:.2f}", False),
        ]
        
        for name, attr, fmt, _ in metrics_to_compare:
            b_val = getattr(base.metrics, attr)
            b_val2 = getattr(best.metrics, attr)
            delta = b_val2 - b_val
            print(f"  {name:20s} {fmt.format(b_val):>22s} {fmt.format(b_val2):>22s} {delta:>+11.2f}")
    
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
