"""Genetic Algorithm correctness tests for ga_optimizer.py.

Tests the GA algorithm logic in isolation using a mock fitness function,
so it does NOT depend on BacktestEngine or any strategy module.

Usage:
    python -m strategy.test_ga_optimizer
    python strategy/test_ga_optimizer.py -v
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.ga_optimizer import (
    PARAM_SPACE,
    FIXED_PARAMS,
    crossover,
    ensure_valid,
    mutate,
    random_individual,
)


# ── Helper: deep validate an individual ─────────────────────────────

def assert_valid_individual(test_case, ind, msg=""):
    """Assert that an individual conforms to PARAM_SPACE and validity rules."""
    # 1. All keys present
    test_case.assertEqual(set(ind.keys()), set(PARAM_SPACE.keys()), f"{msg}: missing/extra keys")

    for name, space in PARAM_SPACE.items():
        val = ind[name]
        if space["type"] == "int":
            # Must be int and in range [low, high] with correct step
            test_case.assertIsInstance(val, int, f"{msg}: {name} should be int, got {type(val)}")
            test_case.assertGreaterEqual(val, space["low"], f"{msg}: {name} < low")
            test_case.assertLessEqual(val, space["high"], f"{msg}: {name} > high")
            # Step alignment
            remainder = (val - space["low"]) % space["step"]
            test_case.assertEqual(remainder, 0, f"{msg}: {name}={val} not aligned to step={space['step']}")

        elif space["type"] == "float":
            test_case.assertIsInstance(val, (int, float), f"{msg}: {name} should be numeric")
            test_case.assertGreaterEqual(val, space["low"], f"{msg}: {name} < low")
            test_case.assertLessEqual(val, space["high"], f"{msg}: {name} > high")

        elif space["type"] == "choice":
            test_case.assertIn(val, space["choices"], f"{msg}: {name}={val} not in choices")

    # 3. Domain constraint: fast < slow
    test_case.assertLess(
        ind["fast_ma_period"], ind["slow_ma_period"],
        f"{msg}: fast_ma_period ({ind['fast_ma_period']}) >= slow_ma_period ({ind['slow_ma_period']})",
    )


# ════════════════════════════════════════════════════════════════════
#  Unit Tests
# ════════════════════════════════════════════════════════════════════

class TestRandomIndividual(unittest.TestCase):
    """Test random_individual() generates valid individuals."""

    def test_all_keys_present(self):
        ind = random_individual()
        self.assertEqual(set(ind.keys()), set(PARAM_SPACE.keys()))

    def test_valid_after_generation(self):
        """100 random individuals should all be valid."""
        for i in range(100):
            ind = random_individual()
            assert_valid_individual(self, ind, f"random_individual #{i}")

    def test_diversity(self):
        """Two random individuals should usually differ."""
        inds = [random_individual() for _ in range(20)]
        # At least some should differ on fast_ma_period
        fast_vals = {ind["fast_ma_period"] for ind in inds}
        self.assertGreater(len(fast_vals), 1, "All random individuals have same fast_ma_period — no diversity")


class TestEnsureValid(unittest.TestCase):
    """Test ensure_valid() fixes fast >= slow constraint."""

    def test_already_valid_unchanged(self):
        ind = {"fast_ma_period": 10, "slow_ma_period": 30}
        result = ensure_valid(ind)
        self.assertEqual(result["fast_ma_period"], 10)
        self.assertEqual(result["slow_ma_period"], 30)

    def test_fast_equals_slow_fixed(self):
        """fast == slow should be fixed."""
        ind = {"fast_ma_period": 30, "slow_ma_period": 30}
        result = ensure_valid(ind)
        self.assertLess(result["fast_ma_period"], result["slow_ma_period"])

    def test_fast_greater_than_slow_fixed(self):
        """fast > slow should be fixed."""
        ind = {"fast_ma_period": 50, "slow_ma_period": 20}
        result = ensure_valid(ind)
        self.assertLess(result["fast_ma_period"], result["slow_ma_period"])

    def test_minimum_fast_not_below_2(self):
        """When slow is at minimum, fast should not drop below 2."""
        ind = {"fast_ma_period": 20, "slow_ma_period": 20}
        result = ensure_valid(ind)
        self.assertGreaterEqual(result["fast_ma_period"], 2)

    def test_full_individual_ensure_valid(self):
        """ensure_valid on a full individual should still produce valid result."""
        for _ in range(50):
            ind = random_individual()
            # Force invalid
            ind["fast_ma_period"] = ind["slow_ma_period"]
            result = ensure_valid(ind)
            assert_valid_individual(self, result, "ensure_valid forced invalid")


class TestCrossover(unittest.TestCase):
    """Test crossover() produces valid offspring."""

    def test_child_has_all_keys(self):
        p1 = random_individual()
        p2 = random_individual()
        child = crossover(p1, p2)
        self.assertEqual(set(child.keys()), set(PARAM_SPACE.keys()))

    def test_child_genes_from_parents(self):
        """Each gene in child must come from either parent."""
        p1 = random_individual()
        p2 = random_individual()
        child = crossover(p1, p2)
        for key in PARAM_SPACE.keys():
            self.assertIn(
                child[key], [p1[key], p2[key]],
                f"child[{key}]={child[key]} not from either parent",
            )

    def test_parents_unchanged(self):
        """Crossover should not modify parents."""
        p1 = random_individual()
        p2 = random_individual()
        p1_copy = p1.copy()
        p2_copy = p2.copy()
        crossover(p1, p2)
        self.assertEqual(p1, p1_copy)
        self.assertEqual(p2, p2_copy)

    def test_crossover_then_ensure_valid(self):
        """Crossover + ensure_valid should always produce valid individual."""
        for _ in range(100):
            p1 = random_individual()
            p2 = random_individual()
            child = crossover(p1, p2)
            child = ensure_valid(child)
            assert_valid_individual(self, child, "crossover+ensure_valid")

    def test_uniform_crossover_distribution(self):
        """Uniform crossover should mix genes roughly 50/50 over many runs."""
        p1 = random_individual()
        p2 = random_individual()
        # Force p1 and p2 to differ on every gene
        p1["fast_ma_period"] = 5
        p2["fast_ma_period"] = 50
        p1["slow_ma_period"] = 20
        p2["slow_ma_period"] = 120
        p1["ma_type"] = "sma"
        p2["ma_type"] = "ema"

        from_p1_count = 0
        trials = 1000
        for _ in range(trials):
            child = crossover(p1, p2)
            if child["fast_ma_period"] == p1["fast_ma_period"]:
                from_p1_count += 1

        # Should be roughly 50% — allow 40-60% range
        ratio = from_p1_count / trials
        self.assertAlmostEqual(ratio, 0.5, delta=0.1, msg=f"Crossover ratio {ratio:.2%} far from 50%")


class TestMutate(unittest.TestCase):
    """Test mutate() stays within bounds."""

    def test_mutate_preserves_keys(self):
        ind = random_individual()
        mutated = mutate(ind, rate=1.0)
        self.assertEqual(set(mutated.keys()), set(PARAM_SPACE.keys()))

    def test_mutate_zero_rate_unchanged(self):
        """mutation_rate=0 should not change anything."""
        ind = random_individual()
        original = ind.copy()
        mutated = mutate(ind, rate=0.0)
        self.assertEqual(mutated, original)

    def test_mutate_full_rate_valid(self):
        """mutation_rate=1.0: all genes re-rolled, should still be valid."""
        for _ in range(100):
            ind = random_individual()
            mutated = mutate(ind, rate=1.0)
            assert_valid_individual(self, mutated, "mutate rate=1.0")

    def test_mutate_within_bounds(self):
        """Mutated values must stay within PARAM_SPACE bounds."""
        for _ in range(200):
            ind = random_individual()
            mutated = mutate(ind, rate=0.5)
            for name, space in PARAM_SPACE.items():
                val = mutated[name]
                if space["type"] == "choice":
                    self.assertIn(val, space["choices"], f"{name} not in choices after mutation")
                else:
                    self.assertGreaterEqual(val, space["low"], f"{name} below low after mutation")
                    self.assertLessEqual(val, space["high"], f"{name} above high after mutation")

    def test_mutate_step_alignment(self):
        """Int mutations should stay on step boundaries."""
        for _ in range(100):
            ind = random_individual()
            mutated = mutate(ind, rate=1.0)
            for name, space in PARAM_SPACE.items():
                if space["type"] == "int":
                    remainder = (mutated[name] - space["low"]) % space["step"]
                    self.assertEqual(remainder, 0, f"{name}={mutated[name]} not step-aligned")


class TestGALoopWithMockFitness(unittest.TestCase):
    """Test the full GA loop using a mock fitness function.

    Instead of running backtests, we define a simple fitness landscape
    with a known optimum, and verify the GA converges toward it.
    """

    def _mock_fitness(self, ind):
        """Mock fitness: reward getting close to a target individual.

        Target: fast=20, slow=60, ma_type='ema', atr_stop=2.5, atr_take=4.0,
                adx_threshold=25.0, regime_chop=14, regime_atr=14

        Fitness = -sum of normalized distances from target.
        """
        target = {
            "fast_ma_period": 20,
            "slow_ma_period": 60,
            "ma_type": "ema",
            "atr_stop_multiplier": 2.5,
            "atr_take_multiplier": 4.0,
            "adx_threshold": 25.0,
            "regime_chop_period": 14,
            "regime_atr_period": 14,
        }

        score = 0.0
        for name, space in PARAM_SPACE.items():
            target_val = target[name]
            actual_val = ind[name]

            if space["type"] == "choice":
                # 1.0 if match, 0.0 if not
                score += 1.0 if actual_val == target_val else 0.0
            else:
                # Normalized distance: 0 = perfect, 1 = max distance
                range_size = space["high"] - space["low"]
                if range_size > 0:
                    distance = abs(actual_val - target_val) / range_size
                    score += 1.0 - distance
                else:
                    score += 1.0

        return round(score, 4)

    def _run_ga_with_mock(
        self,
        population_size=30,
        generations=40,
        mutation_rate=0.2,
        elite_count=2,
        tournament_size=3,
        seed=42,
    ):
        """Run GA with mock fitness, return best individual and history."""
        random.seed(seed)

        population = [ensure_valid(random_individual()) for _ in range(population_size)]
        best_ever = None
        best_ever_fit = -999
        history = []  # (generation, best_fitness)

        for gen in range(generations):
            # Evaluate
            evaluated = []
            for ind in population:
                f = self._mock_fitness(ind)
                evaluated.append((f, ind))

            evaluated.sort(key=lambda x: x[0], reverse=True)

            if evaluated[0][0] > best_ever_fit:
                best_ever = evaluated[0][1].copy()
                best_ever_fit = evaluated[0][0]

            history.append((gen + 1, best_ever_fit))

            # Elitism
            next_gen = [e[1].copy() for e in evaluated[:elite_count]]

            # Tournament + crossover + mutate
            while len(next_gen) < population_size:
                pool1 = random.sample(evaluated, tournament_size)
                p1 = max(pool1, key=lambda x: x[0])[1].copy()
                pool2 = random.sample(evaluated, tournament_size)
                p2 = max(pool2, key=lambda x: x[0])[1].copy()

                child = crossover(p1, p2)
                child = ensure_valid(child)
                child = mutate(child, mutation_rate)
                next_gen.append(child)

            population = next_gen

        return best_ever, best_ever_fit, history

    def test_convergence_improves(self):
        """GA should improve fitness over generations."""
        best, best_fit, history = self._run_ga_with_mock(
            population_size=30, generations=40, seed=42,
        )
        early_avg = sum(h[1] for h in history[:5]) / 5
        late_avg = sum(h[1] for h in history[-5:]) / 5

        self.assertGreater(
            late_avg, early_avg,
            f"GA did not improve: early_avg={early_avg:.3f}, late_avg={late_avg:.3f}",
        )

    def test_finds_good_solution(self):
        """GA should find a solution close to the known optimum."""
        best, best_fit, history = self._run_ga_with_mock(
            population_size=50, generations=60, seed=42,
        )
        # Max possible fitness = 8 (8 params, each contributes 0-1)
        # A good GA should reach at least 6.0 (75% of optimum)
        self.assertGreater(
            best_fit, 6.0,
            f"GA best fitness {best_fit:.3f} too low (max=8.0). Best individual: {best}",
        )

    def test_best_individual_valid(self):
        """Best individual found by GA should be valid."""
        best, best_fit, history = self._run_ga_with_mock(seed=42)
        assert_valid_individual(self, best, "GA best individual")

    def test_elitism_preserves_best(self):
        """With elite_count=1, the best individual should never get worse."""
        best, best_fit, history = self._run_ga_with_mock(
            population_size=20, generations=30, elite_count=1, seed=42,
        )
        # Best fitness should be monotonically non-decreasing
        prev_fit = -999
        for gen, fit in history:
            self.assertGreaterEqual(
                fit, prev_fit,
                f"Fitness decreased at gen {gen}: {fit} < {prev_fit}",
            )
            prev_fit = fit

    def test_different_seeds_both_converge(self):
        """GA should converge regardless of random seed."""
        for seed in [42, 123, 999]:
            best, best_fit, history = self._run_ga_with_mock(
                population_size=30, generations=40, seed=seed,
            )
            self.assertGreater(
                best_fit, 5.0,
                f"Seed {seed}: fitness {best_fit:.3f} too low",
            )

    def test_higher_mutation_exploration(self):
        """Higher mutation rate should explore more but converge slower."""
        # Low mutation: should converge quickly
        _, fit_low, hist_low = self._run_ga_with_mock(
            population_size=30, generations=30, mutation_rate=0.1, seed=42,
        )
        # High mutation: more disruption, might have different trajectory
        _, fit_high, hist_high = self._run_ga_with_mock(
            population_size=30, generations=30, mutation_rate=0.8, seed=42,
        )
        # Both should eventually reach decent fitness
        self.assertGreater(fit_low, 4.0, "Low mutation GA didn't converge")
        self.assertGreater(fit_high, 4.0, "High mutation GA didn't converge")

    def test_population_size_effect(self):
        """Larger population should find better solutions (on average)."""
        _, fit_small, _ = self._run_ga_with_mock(
            population_size=10, generations=40, seed=42,
        )
        _, fit_large, _ = self._run_ga_with_mock(
            population_size=50, generations=40, seed=42,
        )
        # Larger population should generally do at least as well
        # (not guaranteed for every seed, but for seed=42 it should)
        self.assertGreaterEqual(
            fit_large, fit_small - 0.5,
            f"Large pop ({fit_large:.3f}) much worse than small pop ({fit_small:.3f})",
        )


class TestParamSpaceSanity(unittest.TestCase):
    """Sanity checks on the PARAM_SPACE definition itself."""

    def test_all_types_recognized(self):
        """Every param should have a recognized type."""
        for name, space in PARAM_SPACE.items():
            self.assertIn(space["type"], {"int", "float", "choice"}, f"{name}: unknown type '{space['type']}'")

    def test_int_ranges_valid(self):
        """Int params: low <= high, step > 0."""
        for name, space in PARAM_SPACE.items():
            if space["type"] == "int":
                self.assertLessEqual(space["low"], space["high"], f"{name}: low > high")
                self.assertGreater(space["step"], 0, f"{name}: step <= 0")

    def test_float_ranges_valid(self):
        """Float params: low <= high, step > 0."""
        for name, space in PARAM_SPACE.items():
            if space["type"] == "float":
                self.assertLessEqual(space["low"], space["high"], f"{name}: low > high")
                self.assertGreater(space["step"], 0, f"{name}: step <= 0")

    def test_fast_ma_range_subset_of_slow(self):
        """fast_ma upper bound should be less than slow_ma upper bound."""
        fast = PARAM_SPACE["fast_ma_period"]
        slow = PARAM_SPACE["slow_ma_period"]
        self.assertLess(
            fast["high"], slow["high"],
            f"fast_ma high ({fast['high']}) should be < slow_ma high ({slow['high']})",
        )

    def test_choices_non_empty(self):
        """Choice params should have at least 2 options."""
        for name, space in PARAM_SPACE.items():
            if space["type"] == "choice":
                self.assertGreaterEqual(len(space["choices"]), 2, f"{name}: choices < 2")

    def test_fixed_params_no_overlap(self):
        """FIXED_PARAMS should not overlap with PARAM_SPACE."""
        overlap = set(FIXED_PARAMS.keys()) & set(PARAM_SPACE.keys())
        self.assertEqual(overlap, set(), f"Fixed and optimizable params overlap: {overlap}")


# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
