"""Run 2024 out-of-sample backtest with top-ranked GA parameters."""
import sys
import logging
import structlog
from pathlib import Path

# Suppress ALL logging before any imports
logging.disable(logging.CRITICAL)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(40),  # CRITICAL only
    logger_factory=structlog.PrintLoggerFactory(),
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import BacktestEngine, BacktestConfig
from strategy.cta.trend_following import TrendFollowingStrategy

# Top-ranked strategy from ga_results_2025.md
strategy = TrendFollowingStrategy('trend_following', {
    'fast_ma_period': 10,
    'slow_ma_period': 20,
    'ma_type': 'sma',
    'atr_stop_multiplier': 3.0,
    'atr_take_multiplier': 3.0,
    'use_adx_filter': True,
    'use_regime_filter': True,
})

engine = BacktestEngine(BacktestConfig(initial_cash=10000, plot_results=False))
result = engine.run_backtest(
    strategy=strategy,
    pair='BTC/USDT',
    timeframe='1h',
    start_date='2024-01-01',
    end_date='2024-12-31',
)

if result.error:
    print(f'Error: {result.error}')
else:
    print('=' * 55)
    print('  2024 Out-of-Sample Backtest Result')
    print('  Strategy: CTA 10/20 SMA, ATR 3.0/3.0')
    print('=' * 55)
    print(f'Total Return:  {result.total_return:.2%}')
    print(f'Trades:        {len(result.trades)}')
    print(f'Max Drawdown:  {result.max_drawdown:.2%}')
    print(f'Sharpe Ratio:  {result.sharpe_ratio:.4f}')
    print(f'Win Rate:      {result.win_rate:.2%}')
    print(f'Initial Cash:  ${result.initial_value:,.2f}')
    print(f'Final Cash:    ${result.final_value:,.2f}')
    if result.trades:
        wins = [t for t in result.trades if t.pnl > 0]
        losses = [t for t in result.trades if t.pnl <= 0]
        print(f'Winning: {len(wins)}, Losing: {len(losses)}')
        if wins:
            print(f'Avg Win:  ${sum(t.pnl for t in wins)/len(wins):.2f}')
        if losses:
            print(f'Avg Loss: ${sum(t.pnl for t in losses)/len(losses):.2f}')
        if wins and losses:
            avg_w = sum(t.pnl for t in wins) / len(wins)
            avg_l = abs(sum(t.pnl for t in losses) / len(losses))
            if avg_l > 0:
                print(f'Profit Factor: {avg_w/avg_l:.2f}')
    print()
    print('--- vs 2025 (training set) ---')
    print('2025: Return +35.16%, Sharpe 0.060, Trades 59, DD 20.70%, WinRate 59%')
