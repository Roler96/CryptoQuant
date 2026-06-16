"""Validate custom backtest against framework BacktestEngine."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from strategies.spring import SpringReversal


def main():
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"Data: {len(df)} bars, {df.index[0]} to {df.index[-1]}")
    
    # Use the production strategy class
    strategy = SpringReversal()
    print(f"Strategy: {strategy.name} v{strategy.version}")
    print(f"Params: {strategy.params}")
    
    # Run via BacktestEngine
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=0.0005,
        slippage=0.0005,
        use_lows_for_stops=True,
    )
    
    result = engine.run(
        df,
        strategy,
        symbol="BTC/USDT",
        stop_loss_pct=strategy.params["stop_pct"],
        take_profit_pct=strategy.params["target_pct"],
        max_hold_bars=strategy.params["hold_hours"],
    )
    
    m = result.metrics
    trades = result.trades
    
    print(f"\n{'='*55}")
    print(f"BACKTEST ENGINE RESULTS (OKX BTC/USDT 1h)")
    print(f"{'='*55}")
    print(f"  Total Trades:       {m.total_trades}")
    print(f"  Total Return:       {m.total_return_pct:+.2f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.2f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:.2f}%")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.2f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.2f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Avg Hold:           {m.avg_hold_hours:.1f}h")
    
    # Exit breakdown
    from collections import Counter
    exit_counts = Counter(t.exit_reason for t in trades)
    print(f"\n  Exit Breakdown:")
    for reason, count in exit_counts.most_common():
        subset = [t for t in trades if t.exit_reason == reason]
        sp = [t.pnl_pct for t in subset]
        pct = count / len(trades) * 100
        print(f"    {reason:15s}: {count:4d} ({pct:5.1f}%)  avg={np.mean(sp):+.2f}%  total={sum(sp):+.1f}%")
    
    # Signal stats
    sig = strategy.generate_signal(df)
    print(f"\n  Signal count: {sig.sum()} ({sig.sum()/len(df)*100:.2f}% of bars)")
    
    # MFE
    mfes = [t.mfe_pct for t in trades]
    print(f"\n  MFE: mean={np.mean(mfes):+.2f}% median={np.median(mfes):+.2f}% max={np.max(mfes):+.2f}%")
    
    # Per-trade Sharpe
    pnls = [t.pnl_pct for t in trades]
    per_trade_sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 else 0
    print(f"  Per-Trade Sharpe: {per_trade_sharpe:+.2f}")
    
    # Time exits MFE
    time_ex = [t for t in trades if t.exit_reason == "time_exit"]
    if time_ex:
        profitable = sum(1 for t in time_ex if t.mfe_pct > 0)
        print(f"  Time-exits profitable: {profitable}/{len(time_ex)} ({profitable/len(time_ex)*100:.1f}%)")


if __name__ == "__main__":
    main()
