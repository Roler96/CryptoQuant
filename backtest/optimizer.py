"""Strategy parameter optimizer.

Supports grid search and random search over strategy parameter spaces,
with train/test split to guard against overfitting.

Usage:
    from backtest.optimizer import ParameterOptimizer, SearchSpace

    space = SearchSpace(
        int_ranges={"fast_ma_period": (5, 20), "slow_ma_period": (20, 60)},
    )
    optimizer = ParameterOptimizer(strategy_name="cta", pair="BTC/USDT", timeframe="1h")
    results = optimizer.grid_search(space, train_days=180, test_days=60)
    optimizer.print_top_results(results, n=10)
"""

import itertools
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from backtest.engine import BacktestEngine
from backtest.models import BacktestConfig, BacktestResult

logger = structlog.get_logger(__name__)


@dataclass
class SearchSpace:
    """Defines the parameter search space for optimization.

    Attributes:
        int_ranges: Dict of param_name -> (min, max, step) for int params.
                   Step defaults to 1 if only (min, max) given.
        float_ranges: Dict of param_name -> (min, max, step) for float params.
        choices: Dict of param_name -> list of allowed values.
        fixed: Dict of param_name -> value for params to keep constant.
    """

    int_ranges: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    int_ranges_step: Dict[str, int] = field(default_factory=dict)
    float_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    float_ranges_step: Dict[str, float] = field(default_factory=dict)
    choices: Dict[str, List[Any]] = field(default_factory=dict)
    fixed: Dict[str, Any] = field(default_factory=dict)

    def generate_grid(self) -> List[Dict[str, Any]]:
        """Generate all parameter combinations for grid search."""
        axes: List[List[Tuple[str, Any]]] = []

        for name, (lo, hi) in self.int_ranges.items():
            step = self.int_ranges_step.get(name, 1)
            values = list(range(lo, hi + 1, step))
            axes.append([(name, v) for v in values])

        for name, (lo, hi) in self.float_ranges.items():
            step = self.float_ranges_step.get(name, 0.1)
            values = []
            v = lo
            while v <= hi + 1e-9:
                values.append(round(v, 6))
                v += step
            axes.append([(name, v) for v in values])

        for name, opts in self.choices.items():
            axes.append([(name, v) for v in opts])

        if not axes:
            return [dict(self.fixed)] if self.fixed else [{}]

        combos = []
        for combo_tuple in itertools.product(*axes):
            d = dict(self.fixed)
            for k, v in combo_tuple:
                d[k] = v
            combos.append(d)

        return combos

    def generate_random(self, n: int) -> List[Dict[str, Any]]:
        """Generate n random parameter combinations."""
        results = []
        for _ in range(n):
            d = dict(self.fixed)
            for name, (lo, hi) in self.int_ranges.items():
                d[name] = random.randint(lo, hi)
            for name, (lo, hi) in self.float_ranges.items():
                d[name] = round(random.uniform(lo, hi), 4)
            for name, opts in self.choices.items():
                d[name] = random.choice(opts)
            results.append(d)
        return results

    @classmethod
    def for_cta(
        cls,
        fast_ma_range: Tuple[int, int] = (5, 20),
        slow_ma_range: Tuple[int, int] = (20, 60),
        ma_types: Optional[List[str]] = None,
        atr_stop_range: Optional[Tuple[float, float]] = None,
        atr_take_range: Optional[Tuple[float, float]] = None,
        adx_threshold_range: Optional[Tuple[float, float]] = None,
        use_rsi: bool = True,
        use_adx: bool = True,
        use_atr_exit: bool = True,
        use_regime: bool = True,
    ) -> "SearchSpace":
        """Create a SearchSpace preset for the CTA trend following strategy.

        Args:
            fast_ma_range: (min, max) for fast_ma_period
            slow_ma_range: (min, max) for slow_ma_period
            ma_types: List of ma_type values to try
            atr_stop_range: (min, max) for atr_stop_multiplier
            atr_take_range: (min, max) for atr_take_multiplier
            adx_threshold_range: (min, max) for adx_threshold
            use_rsi: Include RSI filter variations
            use_adx: Include ADX filter variations
            use_atr_exit: Include ATR exit variations
            use_regime: Include regime filter variations
        """
        space = cls(
            int_ranges={"fast_ma_period": fast_ma_range, "slow_ma_period": slow_ma_range},
        )
        if ma_types:
            space.choices["ma_type"] = ma_types
        if atr_stop_range:
            space.float_ranges["atr_stop_multiplier"] = atr_stop_range
            space.float_ranges_step["atr_stop_multiplier"] = 0.5
        if atr_take_range:
            space.float_ranges["atr_take_multiplier"] = atr_take_range
            space.float_ranges_step["atr_take_multiplier"] = 0.5
        if adx_threshold_range:
            space.float_ranges["adx_threshold"] = adx_threshold_range
            space.float_ranges_step["adx_threshold"] = 5.0
        space.fixed = {
            "use_rsi_filter": use_rsi,
            "use_adx_filter": use_adx,
            "use_atr_exit": use_atr_exit,
            "use_regime_filter": use_regime,
        }
        return space


@dataclass
class OptimizerResult:
    """Result of a single optimization run.

    Attributes:
        params: The parameter combination used
        train_result: BacktestResult on training period
        test_result: BacktestResult on test period (None if no split)
        score: Composite score for ranking
    """

    params: Dict[str, Any]
    train_result: BacktestResult
    test_result: Optional[BacktestResult] = None
    score: float = 0.0

    @property
    def train_return(self) -> float:
        return self.train_result.total_return

    @property
    def test_return(self) -> float:
        return self.test_result.total_return if self.test_result else 0.0

    @property
    def train_sharpe(self) -> Optional[float]:
        return self.train_result.sharpe_ratio

    @property
    def test_sharpe(self) -> Optional[float]:
        return self.test_result.sharpe_ratio if self.test_result else None

    @property
    def train_dd(self) -> Optional[float]:
        return self.train_result.max_drawdown

    @property
    def test_dd(self) -> Optional[float]:
        return self.test_result.max_drawdown if self.test_result else None


def compute_score(
    result: BacktestResult,
    return_weight: float = 0.3,
    sharpe_weight: float = 0.4,
    dd_weight: float = 0.3,
) -> float:
    """Compute a composite score for ranking backtest results.

    Higher is better. Penalizes drawdown, rewards return and Sharpe.

    Args:
        result: Backtest result to score
        return_weight: Weight for total return
        sharpe_weight: Weight for Sharpe ratio
        dd_weight: Weight for max drawdown (penalized)

    Returns:
        Composite score
    """
    ret = result.total_return
    sharpe = result.sharpe_ratio or 0.0
    dd = result.max_drawdown or 0.0

    # Normalize sharpe to 0-1 range (clamp -1 to 3 → 0 to 1)
    sharpe_norm = max(0.0, min((sharpe + 1.0) / 4.0, 1.0))

    # Normalize return to 0-1 range (clamp -0.5 to 1.0 → 0 to 1)
    ret_norm = max(0.0, min((ret + 0.5) / 1.5, 1.0))

    # Drawdown penalty (0 dd → 1, 50% dd → 0)
    dd_norm = max(0.0, 1.0 - dd * 2.0)

    return ret_norm * return_weight + sharpe_norm * sharpe_weight + dd_norm * dd_weight


class ParameterOptimizer:
    """Strategy parameter optimizer with train/test split.

    Runs grid search or random search over a parameter space,
    evaluates on training data, and optionally validates on test data
    to guard against overfitting.

    Usage:
        optimizer = ParameterOptimizer("cta", "BTC/USDT", "1h")
        space = SearchSpace.for_cta()
        results = optimizer.grid_search(space, train_days=180, test_days=60)
        optimizer.print_top_results(results)
    """

    def __init__(
        self,
        strategy_name: str = "cta",
        pair: str = "BTC/USDT",
        timeframe: str = "1h",
        initial_cash: float = 10000.0,
        commission: float = 0.001,
        slippage: float = 0.0005,
    ) -> None:
        self.strategy_name = strategy_name
        self.pair = pair
        self.timeframe = timeframe
        self.bt_config = BacktestConfig(
            initial_cash=initial_cash,
            commission=commission,
            slippage=slippage,
            plot_results=False,
        )
        self.logger = structlog.get_logger(__name__).bind(
            strategy=strategy_name, pair=pair, timeframe=timeframe,
        )

    def _run_single(
        self,
        params: Dict[str, Any],
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BacktestResult:
        """Run a single backtest with given params."""
        engine = BacktestEngine(self.bt_config)
        strategy = engine.load_strategy(self.strategy_name, params=params)
        return engine.run_backtest(
            strategy, self.pair, self.timeframe,
            days=days, start_date=start_date, end_date=end_date,
        )

    def grid_search(
        self,
        space: SearchSpace,
        train_days: Optional[int] = None,
        test_days: Optional[int] = None,
        train_start: Optional[str] = None,
        train_end: Optional[str] = None,
        test_start: Optional[str] = None,
        test_end: Optional[str] = None,
        top_n: int = 20,
    ) -> List[OptimizerResult]:
        """Run grid search over parameter space.

        If test period is specified, first runs all combinations on train,
        then validates top_n on test period.

        Args:
            space: Parameter search space
            train_days: Training period in days
            test_days: Test period in days (0 = no validation)
            train_start/train_end: Training date range
            test_start/test_end: Test date range
            top_n: Number of top train results to validate on test

        Returns:
            List of OptimizerResult sorted by composite score
        """
        combos = space.generate_grid()
        total = len(combos)
        self.logger.info("grid_search_start", total_combinations=total)

        # Phase 1: Train
        train_results = self._evaluate_combinations(
            combos,
            days=train_days,
            start_date=train_start,
            end_date=train_end,
            phase="train",
        )

        # Sort by train score
        train_results.sort(key=lambda r: r.score, reverse=True)

        # Phase 2: Test validation (top N)
        if test_days or test_start:
            top_combos = [r.params for r in train_results[:top_n]]
            self.logger.info("grid_search_test", validating=len(top_combos))

            test_results = self._evaluate_combinations(
                top_combos,
                days=test_days,
                start_date=test_start,
                end_date=test_end,
                phase="test",
            )

            # Merge test results
            test_by_params = {}
            for tr in test_results:
                key = _params_key(tr.params)
                test_by_params[key] = tr.train_result

            for tr in train_results[:top_n]:
                key = _params_key(tr.params)
                if key in test_by_params:
                    tr.test_result = test_by_params[key]
                    # Re-score using test data if available
                    tr.score = compute_score(test_by_params[key])

            # Re-sort by test score for top results
            train_results.sort(key=lambda r: r.score, reverse=True)

        return train_results

    def random_search(
        self,
        space: SearchSpace,
        n_trials: int = 50,
        train_days: Optional[int] = None,
        test_days: Optional[int] = None,
        train_start: Optional[str] = None,
        train_end: Optional[str] = None,
        test_start: Optional[str] = None,
        test_end: Optional[str] = None,
        top_n: int = 10,
    ) -> List[OptimizerResult]:
        """Run random search over parameter space.

        Args:
            space: Parameter search space
            n_trials: Number of random combinations to try
            train_days/test_days: Period lengths
            train_start/train_end/test_start/test_end: Date ranges
            top_n: Number of top results to validate

        Returns:
            List of OptimizerResult sorted by composite score
        """
        combos = space.generate_random(n_trials)
        self.logger.info("random_search_start", n_trials=n_trials)

        train_results = self._evaluate_combinations(
            combos,
            days=train_days,
            start_date=train_start,
            end_date=train_end,
            phase="train",
        )

        train_results.sort(key=lambda r: r.score, reverse=True)

        if test_days or test_start:
            top_combos = [r.params for r in train_results[:top_n]]
            self.logger.info("random_search_test", validating=len(top_combos))

            test_results = self._evaluate_combinations(
                top_combos,
                days=test_days,
                start_date=test_start,
                end_date=test_end,
                phase="test",
            )

            test_by_params = {}
            for tr in test_results:
                key = _params_key(tr.params)
                test_by_params[key] = tr.train_result

            for tr in train_results[:top_n]:
                key = _params_key(tr.params)
                if key in test_by_params:
                    tr.test_result = test_by_params[key]
                    tr.score = compute_score(test_by_params[key])

            train_results.sort(key=lambda r: r.score, reverse=True)

        return train_results

    def _evaluate_combinations(
        self,
        combos: List[Dict[str, Any]],
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        phase: str = "train",
    ) -> List[OptimizerResult]:
        """Evaluate a list of parameter combinations."""
        results = []
        total = len(combos)
        start_time = time.perf_counter()

        for i, params in enumerate(combos):
            bt_result = self._run_single(
                params, days=days, start_date=start_date, end_date=end_date,
            )

            score = compute_score(bt_result) if not bt_result.error else -1.0
            opt_result = OptimizerResult(
                params=params,
                train_result=bt_result,
                score=score,
            )
            results.append(opt_result)

            if (i + 1) % 10 == 0 or (i + 1) == total:
                elapsed = time.perf_counter() - start_time
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                self.logger.info(
                    f"{phase}_progress",
                    completed=i + 1,
                    total=total,
                    rate=f"{rate:.1f}/s",
                    best_score=max(r.score for r in results) if results else 0,
                )

        return results

    @staticmethod
    def print_top_results(results: List[OptimizerResult], n: int = 10) -> None:
        """Print top N optimization results in a readable table.

        Args:
            results: List of optimizer results (should be pre-sorted)
            n: Number of results to display
        """
        top = results[:n]

        if not top:
            print("No results to display.")
            return

        # Determine which params vary
        all_keys = set()
        for r in top:
            all_keys.update(r.params.keys())
        param_keys = sorted(all_keys)

        has_test = any(r.test_result is not None for r in top)

        # Header
        print("\n" + "=" * 120)
        print("  PARAMETER OPTIMIZATION RESULTS (Top {})".format(n))
        print("=" * 120)

        # Column widths
        headers = ["#", "Return%", "Sharpe", "MaxDD%", "Trades", "Score"]
        if has_test:
            headers += ["Test_Ret%", "Test_Sharpe", "Test_DD%"]

        # Param columns
        param_headers = [k[:12] for k in param_keys]
        all_headers = headers + param_headers

        # Print header
        header_line = "  ".join(f"{h:>12}" for h in all_headers)
        print(header_line)
        print("-" * len(header_line))

        # Print rows
        for i, r in enumerate(top):
            train = r.train_result
            cols = [
                f"{i + 1:>12}",
                f"{train.total_return * 100:>11.2f}%",
                f"{train.sharpe_ratio or 0:>12.4f}",
                f"{(train.max_drawdown or 0) * 100:>11.2f}%",
                f"{len(train.trades):>12}",
                f"{r.score:>12.4f}",
            ]

            if has_test and r.test_result:
                test = r.test_result
                cols += [
                    f"{test.total_return * 100:>11.2f}%",
                    f"{test.sharpe_ratio or 0:>12.4f}",
                    f"{(test.max_drawdown or 0) * 100:>11.2f}%",
                ]
            elif has_test:
                cols += ["N/A"] * 3

            # Param values
            for k in param_keys:
                v = r.params.get(k, "")
                cols.append(f"{str(v):>12}")

            print("  ".join(cols))

        print("=" * 120)

        # Best result details
        if top:
            best = top[0]
            print(f"\n  Best Parameters:")
            for k, v in best.params.items():
                print(f"    {k}: {v}")
            train = best.train_result
            print(f"\n  Train: Return={train.total_return:.2%}, "
                  f"Sharpe={train.sharpe_ratio:.4f}, "
                  f"MaxDD={train.max_drawdown:.2%}, "
                  f"Trades={len(train.trades)}")
            if best.test_result:
                test = best.test_result
                print(f"  Test:  Return={test.total_return:.2%}, "
                      f"Sharpe={test.sharpe_ratio:.4f}, "
                      f"MaxDD={test.max_drawdown:.2%}, "
                      f"Trades={len(test.trades)}")
            print()


    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d: Dict[str, Any] = {
            "params": self.params,
            "score": self.score,
            "train": {
                "return": self.train_result.total_return,
                "sharpe": self.train_result.sharpe_ratio,
                "max_drawdown": self.train_result.max_drawdown,
                "trades": len(self.train_result.trades),
                "initial_value": self.train_result.initial_value,
                "final_value": self.train_result.final_value,
            },
        }
        if self.test_result:
            d["test"] = {
                "return": self.test_result.total_return,
                "sharpe": self.test_result.sharpe_ratio,
                "max_drawdown": self.test_result.max_drawdown,
                "trades": len(self.test_result.trades),
                "initial_value": self.test_result.initial_value,
                "final_value": self.test_result.final_value,
            }
        return d


def save_results(
    results: List[OptimizerResult],
    filepath: str = "logs/optimizer_results.json",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Save optimization results to JSON file.

    Args:
        results: List of optimizer results
        filepath: Output file path
        metadata: Optional metadata to include (strategy, pair, timeframe, etc.)

    Returns:
        Path to saved file
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "metadata": metadata or {},
        "total_combinations": len(results),
        "results": [r.to_dict() for r in results],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    logger.info("results_saved", path=str(path), count=len(results))
    return str(path)


def load_results(filepath: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Load optimization results from JSON file.

    Args:
        filepath: Path to JSON results file

    Returns:
        Tuple of (metadata, list of result dicts)
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("metadata", {}), data.get("results", [])


def load_best_params(filepath: str) -> Dict[str, Any]:
    """Load the best (top-scoring) parameters from a saved results file.

    Args:
        filepath: Path to JSON results file

    Returns:
        Dict of parameter names to values
    """
    _, results = load_results(filepath)
    if not results:
        return {}
    best = max(results, key=lambda r: r.get("score", -1))
    return best.get("params", {})


def apply_best_params(
    strategy_name: str = "cta",
    filepath: str = "logs/optimizer_results.json",
    pair: str = "BTC/USDT",
    timeframe: str = "1h",
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> BacktestResult:
    """Load best params from file and run backtest with them.

    Convenience function: load best params → create strategy → run backtest.

    Args:
        strategy_name: Strategy to use
        filepath: Path to saved optimizer results
        pair: Trading pair
        timeframe: Candle timeframe
        days: Backtest period in days
        start_date: Backtest start date
        end_date: Backtest end date

    Returns:
        BacktestResult
    """
    best_params = load_best_params(filepath)
    logger.info("applying_best_params", params=best_params)

    engine = BacktestEngine(BacktestConfig(plot_results=True))
    strategy = engine.load_strategy(strategy_name, params=best_params)
    return engine.run_backtest(
        strategy, pair, timeframe,
        days=days, start_date=start_date, end_date=end_date,
    )


def _params_key(params: Dict[str, Any]) -> str:
    """Create a hashable key from params dict for lookup."""
    return str(sorted(params.items()))
