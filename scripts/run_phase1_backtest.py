"""Run Phase 1 quantitative strategy backtests.

This script:
1. Downloads 2025 data for multiple trading pairs (if not already present)
2. Runs three strategies:
   - Cross-sectional multi-factor
   - Funding rate arbitrage
   - Basis mean reversion
3. Outputs performance comparison report

Usage:
    python scripts/run_phase1_backtest.py [--pairs BTC/USDT ETH/USDT ...] [--start-date 2025-01-01] [--end-date 2025-05-01]
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import structlog

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtest.multi_asset.engine import MultiAssetBacktestEngine, MultiAssetBacktestConfig
from backtest.multi_asset.data_loader import MultiAssetDataLoader, download_missing_pairs
from strategy.quant.cross_sectional import CrossSectionalMultiFactorStrategy, MomentumOnlyStrategy
from strategy.quant.funding_rate_arb import FundingRateArbitrageStrategy
from strategy.quant.basis_strategy import BasisMeanReversionStrategy

logger = structlog.get_logger(__name__)


# Default pairs for cross-sectional strategy
DEFAULT_PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "LTC/USDT",
    "BCH/USDT",
    "NEAR/USDT",
    "APT/USDT",
    "ARB/USDT",
    "OP/USDT",
    "INJ/USDT",
    "SUI/USDT",
    "SEI/USDT",
]


def format_results_table(results: List[Dict[str, Any]]) -> str:
    """Format results as ASCII table."""
    lines = []
    lines.append("=" * 80)
    lines.append("PHASE 1 QUANTITATIVE STRATEGIES - BACKTEST RESULTS")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Strategy Comparison:")
    lines.append("-" * 80)
    lines.append(f"{'Strategy':<30} {'Return':>12} {'Sharpe':>10} {'MaxDD':>10} {'Trades':>8}")
    lines.append("-" * 80)

    for r in results:
        name = r.get("strategy_name", r.get("strategy", "unknown"))
        ret = r.get("total_return", 0)
        sharpe = r.get("sharpe_ratio") or "N/A"
        max_dd = r.get("max_drawdown") or "N/A"
        trades = r.get("total_trades", 0)

        ret_str = f"{ret * 100:.2f}%"
        sharpe_str = f"{sharpe:.2f}" if isinstance(sharpe, float) else sharpe
        dd_str = f"{max_dd * 100:.2f}%" if isinstance(max_dd, float) else max_dd

        lines.append(f"{name:<30} {ret_str:>12} {sharpe_str:>10} {dd_str:>10} {trades:>8}")

    lines.append("-" * 80)
    lines.append("")
    return "\n".join(lines)


def format_strategy_details(result: Dict[str, Any]) -> str:
    """Format detailed strategy output."""
    lines = []
    lines.append("=" * 80)
    lines.append(f"STRATEGY: {result.get('strategy_name', result.get('strategy', 'unknown'))}")
    lines.append("=" * 80)

    if "error" in result:
        lines.append(f"ERROR: {result['error']}")
        return "\n".join(lines)

    lines.append(f"Pairs: {result.get('pairs', ['N/A'])}")
    lines.append(f"Timeframe: {result.get('timeframe', 'N/A')}")
    lines.append(f"Period: {result.get('start_date', 'N/A')} to {result.get('end_date', 'N/A')}")
    lines.append("")
    lines.append("Performance:")
    lines.append(f"  Initial Value: ${result.get('initial_value', 0):,.2f}")
    lines.append(f"  Final Value:   ${result.get('final_value', 0):,.2f}")
    lines.append(f"  Total Return:  {result.get('total_return', 0) * 100:.2f}%")

    sharpe = result.get("sharpe_ratio")
    if sharpe:
        lines.append(f"  Sharpe Ratio:  {sharpe:.3f}")

    max_dd = result.get("max_drawdown")
    if max_dd:
        lines.append(f"  Max Drawdown:  {max_dd * 100:.2f}%")

    calmar = result.get("calmar_ratio")
    if calmar:
        lines.append(f"  Calmar Ratio:  {calmar:.3f}")

    lines.append("")
    lines.append(f"Total Trades: {result.get('total_trades', 0)}")

    # Funding arb specific
    if "total_funding_collected" in result:
        lines.append(f"Funding Collected: ${result['total_funding_collected']:,.2f}")

    # Turnover
    if "turnover" in result:
        lines.append(f"Turnover: {result['turnover']:.2f}x")

    # Exposures
    if "long_exposure_avg" in result:
        lines.append(f"Avg Long Exposure: {result['long_exposure_avg'] * 100:.1f}%")
        lines.append(f"Avg Short Exposure: {result['short_exposure_avg'] * 100:.1f}%")

    # Basis stats
    if "basis_stats" in result:
        bs = result["basis_stats"]
        lines.append("")
        lines.append("Basis Statistics:")
        lines.append(f"  Mean: {bs['mean'] * 100:.3f}%")
        lines.append(f"  Std:  {bs['std'] * 100:.3f}%")
        lines.append(f"  Max:  {bs['max'] * 100:.3f}%")
        lines.append(f"  Min:  {bs['min'] * 100:.3f}%")

    # Winning trades
    if "winning_trades" in result:
        total = result.get("total_trades", 0)
        wins = result["winning_trades"]
        if total > 0:
            win_rate = wins / total
            lines.append(f"Win Rate: {win_rate * 100:.1f}% ({wins}/{total})")

    lines.append("")
    return "\n".join(lines)


def run_cross_sectional_backtest(
    pairs: List[str],
    timeframe: str,
    start_date: str,
    end_date: str,
    initial_cash: float = 100000.0,
) -> Dict[str, Any]:
    """Run cross-sectional multi-factor backtest."""
    logger.info("running_cross_sectional_backtest", pairs=len(pairs))

    engine = MultiAssetBacktestEngine(
        MultiAssetBacktestConfig(
            initial_cash=initial_cash,
            commission=0.0005,
            gross_exposure=2.0,  # 100% long + 100% short
            rebalance_frequency="1d",
        )
    )

    strategy = CrossSectionalMultiFactorStrategy(
        name="cross_sectional_multifactor",
        params={
            "momentum_period": 30,
            "vol_period": 30,
            "factor_weights": {
                "momentum": 0.35,
                "carry": 0.25,
                "size": 0.20,
                "low_vol": 0.20,
            },
        },
    )

    result = engine.run_backtest(
        strategy=strategy,
        pairs=pairs,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
    )

    return result.to_dict()


def run_funding_rate_backtest(
    pairs: List[str],
    timeframe: str,
    start_date: str,
    end_date: str,
    initial_cash: float = 100000.0,
) -> Dict[str, Any]:
    """Run funding rate arbitrage backtest."""
    logger.info("running_funding_rate_backtest", pairs=len(pairs))

    data_loader = MultiAssetDataLoader()

    # Load price data
    try:
        prices_df = data_loader.get_close_prices(pairs, timeframe, start_date, end_date)
    except Exception as e:
        logger.error("failed_to_load_data", error=str(e))
        return {"error": str(e), "strategy": "funding_rate_arb"}

    strategy = FundingRateArbitrageStrategy(
        name="funding_rate_arb",
        params={
            "min_funding_rate": 0.0001,
            "position_size_pct": 0.95,
            "max_hold_periods": 168,
        },
    )

    result = strategy.backtest_multi_pair(
        pairs=pairs,
        prices_df=prices_df,
        timeframe=timeframe,
        start_cash=initial_cash,
        allocation_per_pair=1.0 / len(pairs),  # Equal allocation
    )

    result["strategy_name"] = "funding_rate_arb"
    result["timeframe"] = timeframe
    result["start_date"] = start_date
    result["end_date"] = end_date

    return result


def run_basis_backtest(
    pairs: List[str],
    timeframe: str,
    start_date: str,
    end_date: str,
    initial_cash: float = 100000.0,
) -> Dict[str, Any]:
    """Run basis mean reversion backtest."""
    logger.info("running_basis_backtest", pairs=len(pairs))

    data_loader = MultiAssetDataLoader()

    # Load price data
    try:
        prices_df = data_loader.get_close_prices(pairs, timeframe, start_date, end_date)
    except Exception as e:
        logger.error("failed_to_load_data", error=str(e))
        return {"error": str(e), "strategy": "basis_mean_reversion"}

    strategy = BasisMeanReversionStrategy(
        params={
            "lookback_period": 20,
            "entry_threshold": 2.0,
            "exit_threshold": 0.5,
            "max_hold_periods": 72,
        },
    )
    strategy.name = "basis_mean_reversion"

    # Run on each pair
    all_results = []
    per_pair_cash = initial_cash / len(pairs)

    for pair in pairs:
        if pair not in prices_df.columns:
            continue

        spot_prices = prices_df[pair]
        result = strategy.backtest_single_pair(
            pair=pair,
            spot_prices=spot_prices,
            timeframe=timeframe,
            start_cash=per_pair_cash,
        )
        all_results.append(result)

    # Aggregate
    final_value = sum(r.get("final_value", per_pair_cash) for r in all_results)
    total_return = (final_value - initial_cash) / initial_cash

    return {
        "strategy_name": "basis_mean_reversion",
        "pairs": pairs,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "initial_value": initial_cash,
        "final_value": final_value,
        "total_return": total_return,
        "individual_results": all_results,
        "total_trades": sum(r.get("total_trades", 0) for r in all_results),
    }


def main():
    """Run Phase 1 backtests."""
    parser = argparse.ArgumentParser(description="Run Phase 1 quantitative strategy backtests")
    parser.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS[:10], help="Trading pairs")
    parser.add_argument("--timeframe", default="1h", help="Candle timeframe")
    parser.add_argument("--start-date", default="2025-01-01", help="Start date")
    parser.add_argument("--end-date", default="2025-05-01", help="End date")
    parser.add_argument("--cash", type=float, default=100000.0, help="Initial capital")
    parser.add_argument("--download", action="store_true", help="Download missing data")
    parser.add_argument("--output", default=None, help="Output JSON file path")

    args = parser.parse_args()

    print("=" * 80)
    print("CRYPTOQUANT PHASE 1 BACKTEST")
    print("=" * 80)
    print(f"Pairs: {len(args.pairs)}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Initial Cash: ${args.cash:,.2f}")
    print()

    # Download missing data if requested
    if args.download:
        print("Downloading missing data...")
        download_missing_pairs(
            pairs=args.pairs,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            sandbox=True,
        )
        print("Download complete.")
        print()

    # Run all three strategies
    all_results = []

    # 1. Cross-sectional multi-factor
    print("Running Cross-Sectional Multi-Factor Strategy...")
    try:
        cs_result = run_cross_sectional_backtest(
            pairs=args.pairs,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_cash=args.cash,
        )
        all_results.append(cs_result)
        print(f"  Total Return: {cs_result.get('total_return', 0) * 100:.2f}%")
    except Exception as e:
        logger.error("cross_sectional_failed", error=str(e))
        all_results.append({"strategy_name": "cross_sectional_multifactor", "error": str(e)})
        print(f"  ERROR: {e}")

    print()

    # 2. Funding rate arbitrage
    print("Running Funding Rate Arbitrage Strategy...")
    try:
        fr_result = run_funding_rate_backtest(
            pairs=args.pairs,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_cash=args.cash,
        )
        all_results.append(fr_result)
        print(f"  Total Return: {fr_result.get('total_return', 0) * 100:.2f}%")
        print(f"  Funding Collected: ${fr_result.get('total_funding_collected', 0):,.2f}")
    except Exception as e:
        logger.error("funding_rate_failed", error=str(e))
        all_results.append({"strategy_name": "funding_rate_arb", "error": str(e)})
        print(f"  ERROR: {e}")

    print()

    # 3. Basis mean reversion
    print("Running Basis Mean Reversion Strategy...")
    try:
        basis_result = run_basis_backtest(
            pairs=args.pairs,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_cash=args.cash,
        )
        all_results.append(basis_result)
        print(f"  Total Return: {basis_result.get('total_return', 0) * 100:.2f}%")
    except Exception as e:
        logger.error("basis_failed", error=str(e))
        all_results.append({"strategy_name": "basis_mean_reversion", "error": str(e)})
        print(f"  ERROR: {e}")

    print()

    # Output results
    print(format_results_table(all_results))
    print()

    # Detailed output
    for result in all_results:
        print(format_strategy_details(result))

    # Save JSON output if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()