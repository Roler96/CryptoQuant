"""Quick target sweep for Spring v1.2.0 — find optimal target using BacktestEngine."""
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
    
    targets = [1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0]
    
    print(f"{'Target':>8s} {'Trades':>7s} {'Return':>8s} {'Sharpe':>7s} {'Sortino':>8s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s} {'TP%':>6s} {'PerTrSh':>8s}")
    print("-" * 85)
    
    for target in targets:
        strategy = SpringReversal(params={
            "target_pct": target,
            "stop_pct": 3.0,
            "hold_hours": 32,
            "sma200_filter": True,
            "bb_filter": True,
            "bb_low": 0.12,
            "bb_high": 0.65,
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
            take_profit_pct=target,
            max_hold_bars=32,
        )
        
        m = result.metrics
        trades = result.trades
        
        # TP rate
        tp_count = sum(1 for t in trades if t.exit_reason == "take_profit")
        tp_pct = tp_count / len(trades) * 100 if trades else 0
        
        # Per-trade Sharpe
        pnls = [t.pnl_pct for t in trades]
        pt_sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
        
        print(f"{target:>8.2f}% {m.total_trades:>7d} {m.total_return_pct:>+7.2f}% {m.sharpe_ratio:>7.2f} {m.sortino_ratio:>+8.2f} {m.max_drawdown_pct:>+6.2f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>6.2f} {tp_pct:>5.1f}% {pt_sharpe:>+8.2f}")
    
    print("\n" + "=" * 85)
    print("Done")


if __name__ == "__main__":
    main()
