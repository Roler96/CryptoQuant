"""Quick BB parameter sweep for Spring — test different BB periods/stds."""
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
    
    # Test different BB configurations
    configs = [
        # (period, std, bb_low, bb_high, label)
        (20, 2.0, 0.12, 0.65, "BB20/2.0 [0.12,0.65)"),
        (20, 2.0, 0.15, 0.60, "BB20/2.0 [0.15,0.60)"),
        (20, 2.0, 0.20, 0.60, "BB20/2.0 [0.20,0.60)"),
        (30, 2.0, 0.12, 0.65, "BB30/2.0 [0.12,0.65)"),
        (30, 2.5, 0.12, 0.65, "BB30/2.5 [0.12,0.65)"),
        (50, 2.5, 0.12, 0.65, "BB50/2.5 [0.12,0.65)"),
        (50, 2.5, 0.15, 0.60, "BB50/2.5 [0.15,0.60)"),
        (50, 2.5, 0.20, 0.60, "BB50/2.5 [0.20,0.60)"),
    ]
    
    print(f"{'Config':35s} {'Trades':>7s} {'Return':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s} {'PerTrSh':>8s}")
    print("-" * 95)
    
    for period, std, bb_low, bb_high, label in configs:
        strategy = SpringReversal(params={
            "target_pct": 2.75,
            "stop_pct": 3.0,
            "hold_hours": 32,
            "sma200_filter": True,
            "bb_filter": True,
            "bb_period": period,
            "bb_std": std,
            "bb_low": bb_low,
            "bb_high": bb_high,
        })
        
        engine = BacktestEngine(
            initial_capital=10_000,
            commission=0.0005,
            slippage=0.0005,
            use_lows_for_stops=True,
        )
        
        result = engine.run(
            df, strategy,
            symbol="BTC/USDT",
            stop_loss_pct=3.0,
            take_profit_pct=2.75,
            max_hold_bars=32,
        )
        
        m = result.metrics
        trades = result.trades
        
        pnls = [t.pnl_pct for t in trades]
        pt_sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
        
        print(f"{label:35s} {m.total_trades:>7d} {m.total_return_pct:>+7.2f}% {m.sharpe_ratio:>7.2f} {m.max_drawdown_pct:>+6.2f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>6.2f} {pt_sharpe:>+8.2f}")
    
    print("\nDone")


if __name__ == "__main__":
    main()
