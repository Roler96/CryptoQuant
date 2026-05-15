"""Genetic Algorithm Parameter Optimizer for CTA Strategy.

Searches for optimal strategy parameters using evolutionary optimization.

Usage:
    python -m strategy.ga_optimizer
    python strategy/ga_optimizer.py --generations 30 --population 20
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import BacktestConfig, BacktestEngine

# Search space definition
PARAM_SPACE = {
    "fast_ma_period": {"type": "int", "low": 5, "high": 50, "step": 1},
    "slow_ma_period": {"type": "int", "low": 20, "high": 120, "step": 5},
    "ma_type": {"type": "choice", "choices": ["sma", "ema"]},
    "atr_stop_multiplier": {"type": "float", "low": 1.5, "high": 4.0, "step": 0.5},
    "atr_take_multiplier": {"type": "float", "low": 2.0, "high": 6.0, "step": 0.5},
    "adx_threshold": {"type": "float", "low": 15.0, "high": 35.0, "step": 5.0},
    "regime_chop_period": {"type": "int", "low": 7, "high": 28, "step": 1},
    "regime_atr_period": {"type": "int", "low": 7, "high": 28, "step": 1},
}

# Fixed params (not optimized)
FIXED_PARAMS = {
    "use_rsi_filter": True,
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "use_adx_filter": True,
    "adx_period": 14,
    "use_regime_filter": True,
    "regime_adx_period": 14,  # will be overridden if regime_chop_period differs
}

START_DATE = "2025-01-01"
END_DATE = "2025-12-31"


def random_individual():
    """Generate a random valid individual."""
    ind = {}
    for name, space in PARAM_SPACE.items():
        if space["type"] == "int":
            steps = range(space["low"], space["high"] + 1, space["step"])
            ind[name] = random.choice(list(steps))
        elif space["type"] == "float":
            steps = []
            v = space["low"]
            while v <= space["high"]:
                steps.append(round(v, 1))
                v += space["step"]
            ind[name] = random.choice(steps)
        elif space["type"] == "choice":
            ind[name] = random.choice(space["choices"])
    return ensure_valid(ind)


def ensure_valid(ind):
    """Ensure individual is valid (fast < slow, all within bounds and step-aligned)."""
    fast = ind["fast_ma_period"]
    slow = ind["slow_ma_period"]

    fast_space = PARAM_SPACE["fast_ma_period"]
    slow_space = PARAM_SPACE["slow_ma_period"]

    def snap_to_step(val, space):
        """Snap value to nearest valid step-aligned value within bounds."""
        # Round to nearest step
        steps_from_low = round((val - space["low"]) / space["step"])
        snapped = space["low"] + steps_from_low * space["step"]
        # Clamp to bounds
        return max(space["low"], min(space["high"], snapped))

    # Fix fast >= slow: swap so larger becomes slow
    if fast >= slow:
        fast, slow = slow, fast

    # If still equal after swap (both same value), nudge apart
    if fast >= slow:
        slow = fast + slow_space["step"]

    # Snap both to their step boundaries
    fast = snap_to_step(fast, fast_space)
    slow = snap_to_step(slow, slow_space)

    # After snapping, fast might again be >= slow — fix by nudging slow up
    if fast >= slow:
        slow = snap_to_step(fast + slow_space["step"], slow_space)

    # Final clamp (should be redundant but safe)
    fast = max(fast_space["low"], min(fast_space["high"], fast))
    slow = max(slow_space["low"], min(slow_space["high"], slow))

    ind["fast_ma_period"] = fast
    ind["slow_ma_period"] = slow
    return ind


def fitness(ind):
    """Evaluate individual fitness (Sharpe ratio)."""
    params = dict(FIXED_PARAMS)
    params.update(ind)

    try:
        e = BacktestEngine(BacktestConfig(initial_cash=10000, plot_results=False))
        s = e.load_strategy("cta", params)
        r = e.run_backtest(s, "BTC/USDT", "1h", start_date=START_DATE, end_date=END_DATE)

        if r.error:
            return -10.0, 0, 0

        # Fitness = Sharpe (penalize if too few trades)
        sharpe = r.sharpe_ratio if r.sharpe_ratio else 0
        trade_penalty = max(0, 10 - len(r.trades)) * 0.01
        return round(sharpe - trade_penalty, 4), len(r.trades), r.total_return
    except Exception:
        return -10.0, 0, 0


def crossover(p1, p2):
    """Uniform crossover."""
    child = {}
    for key in p1:
        child[key] = p1[key] if random.random() < 0.5 else p2[key]
    return child


def mutate(ind, rate=0.2):
    """Random mutation."""
    for name, space in PARAM_SPACE.items():
        if random.random() < rate:
            if space["type"] == "int":
                steps = range(space["low"], space["high"] + 1, space["step"])
                ind[name] = random.choice(list(steps))
            elif space["type"] == "float":
                steps = []
                v = space["low"]
                while v <= space["high"]:
                    steps.append(round(v, 1))
                    v += space["step"]
                ind[name] = random.choice(steps)
            elif space["type"] == "choice":
                ind[name] = random.choice(space["choices"])
    return ensure_valid(ind)


def run_ga(
    population_size=20,
    generations=20,
    mutation_rate=0.2,
    elite_count=2,
    tournament_size=3,
):
    print(f"GA Optimizer: pop={population_size}, gen={generations}")
    print(f"Fitness: Sharpe ratio (penalize < 10 trades)")
    print(f"Period: {START_DATE} ~ {END_DATE}")
    print()

    # Initialize population
    population = [ensure_valid(random_individual()) for _ in range(population_size)]

    best_ever = random_individual()
    best_ever_fit = -999

    for gen in range(generations):
        t0 = time.time()

        # Evaluate fitness
        evaluated = []
        for ind in population:
            f, trades, ret = fitness(ind)
            evaluated.append((f, ind, trades, ret))

        evaluated.sort(key=lambda x: x[0], reverse=True)

        # Track best
        if evaluated[0][0] > best_ever_fit:
            best_ever = evaluated[0][1].copy()
            best_ever_fit = evaluated[0][0]

        # Elitism
        next_gen = [e[1].copy() for e in evaluated[:elite_count]]

        # Tournament selection + crossover + mutation
        while len(next_gen) < population_size:
            # Select parents
            pool1 = random.sample(evaluated, tournament_size)
            p1 = max(pool1, key=lambda x: x[0])[1].copy()
            pool2 = random.sample(evaluated, tournament_size)
            p2 = max(pool2, key=lambda x: x[0])[1].copy()

            # Crossover
            child = crossover(p1, p2)
            child = ensure_valid(child)
            child = mutate(child, mutation_rate)
            next_gen.append(child)

        population = next_gen

        elapsed = time.time() - t0
        top = evaluated[0]
        print(f"  Gen {gen+1:3d}: best={top[0]:+.4f}  ret={top[3]:+.2%}  trades={top[2]:3d}  time={elapsed:.1f}s")

        # Print top 3
        for i, (f, ind, trades, ret) in enumerate(evaluated[:3]):
            print(f"    #{i+1}: fast={ind['fast_ma_period']}, slow={ind['slow_ma_period']}, "
                  f"ma={ind['ma_type']}, ATR_S={ind['atr_stop_multiplier']}x, ATR_T={ind['atr_take_multiplier']}x, "
                  f"ADX={ind['adx_threshold']}, CHOP={ind['regime_chop_period']}, ATR_P={ind['regime_atr_period']}")

    print()
    print(f"Best ever fitness: {best_ever_fit:.4f}")
    print(f"Best params: {json.dumps(best_ever, indent=2)}")

    # Verify best
    params = dict(FIXED_PARAMS)
    params.update(best_ever)
    e = BacktestEngine(BacktestConfig(initial_cash=10000, plot_results=False))
    s = e.load_strategy("cta", params)
    r = e.run_backtest(s, "BTC/USDT", "1h", start_date=START_DATE, end_date=END_DATE)

    print(f"\nFinal verification:")
    print(f"  Return: {r.total_return:+.2%}")
    print(f"  Trades: {len(r.trades)}")
    print(f"  MaxDD:  {r.max_drawdown:.2%}")
    print(f"  Sharpe: {r.sharpe_ratio:+.4f}")

    return best_ever


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GA Parameter Optimizer")
    parser.add_argument("--generations", "-g", type=int, default=20)
    parser.add_argument("--population", "-p", type=int, default=20)
    parser.add_argument("--mutation", "-m", type=float, default=0.2)
    parser.add_argument("--elite", "-e", type=int, default=2)
    parser.add_argument("--output", "-o", default="/tmp/ga_best.json")
    args = parser.parse_args()

    best = run_ga(
        population_size=args.population,
        generations=args.generations,
        mutation_rate=args.mutation,
        elite_count=args.elite,
    )

    with open(args.output, "w") as f:
        json.dump(best, f)
    print(f"\nSaved to {args.output}")
