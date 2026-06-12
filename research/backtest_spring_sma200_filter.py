"""
Spring Reversal — SMA200 Filter + Regime Analysis + Walk-Forward Validation
============================================================================

Research question: Spring has Sharpe 2.72 but one negative WF split (2022 bear).
Does adding SMA200 filter fix the bear-market weakness without destroying alpha?

Methodology:
1. Baseline Spring (no filter) — confirm known results
2. Spring + SMA200 filter — only trade when price > SMA(200)
3. Regime analysis — tag every trade with market conditions at entry
4. Walk-forward validation — 6 splits for each variant
5. Additional combos: SMA200 + cooldown, SMA200 + ADX filter
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import new_low_bullish, sma, adx


# ---------------------------------------------------------------------------
# Strategy variants
# ---------------------------------------------------------------------------

class SpringBaseline(Strategy):
    """Plain Spring Reversal — no filter."""
    timeframe = "1h"
    min_bars = 100
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_Baseline"

    def generate_signal(self, df):
        df = self.preprocess(df)
        return new_low_bullish(df, lookback=self.params["lookback"])


class SpringSMA200(Strategy):
    """Spring + SMA200 filter: only long when price > SMA(200)."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_SMA200"

    def generate_signal(self, df):
        df = self.preprocess(df)
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        sma_val = sma(df["close"], self.params["sma_period"])
        # Only take signal when price is above SMA200
        above_sma = df["close"] > sma_val
        return (spring_sig * above_sma.astype(int)).clip(lower=0)


class SpringSMA150(Strategy):
    """Spring + SMA150 filter."""
    timeframe = "1h"
    min_bars = 200
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "sma_period": 150, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_SMA150"

    def generate_signal(self, df):
        df = self.preprocess(df)
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        sma_val = sma(df["close"], self.params["sma_period"])
        above_sma = df["close"] > sma_val
        return (spring_sig * above_sma.astype(int)).clip(lower=0)


class SpringEMA50(Strategy):
    """Spring + EMA50 filter: only long when price > EMA(50)."""
    timeframe = "1h"
    min_bars = 100
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "ema_period": 50, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_EMA50"

    def generate_signal(self, df):
        df = self.preprocess(df)
        from cryptoquant.strategy.signals import ema
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        ema_val = ema(df["close"], self.params["ema_period"])
        above_ema = df["close"] > ema_val
        return (spring_sig * above_ema.astype(int)).clip(lower=0)


class SpringSMA200Cooldown(Strategy):
    """Spring + SMA200 + consecutive-loss cooldown (2 stops → skip 12 bars)."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_SMA200_Cooldown"

    def generate_signal(self, df):
        # Cooldown is applied at the engine simulation level, not signal level.
        # For signal generation, this is identical to SMA200.
        df = self.preprocess(df)
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        sma_val = sma(df["close"], self.params["sma_period"])
        above_sma = df["close"] > sma_val
        return (spring_sig * above_sma.astype(int)).clip(lower=0)


# ---------------------------------------------------------------------------
# Regime tagging
# ---------------------------------------------------------------------------

def tag_trade_regimes(trades, df):
    """Tag each trade with market conditions at entry time."""
    # Pre-compute indicators
    sma200 = sma(df["close"], 200)
    sma50 = sma(df["close"], 50)
    adx_data = adx(df, 14)
    atr14 = df["close"].pct_change().rolling(24).std()  # simplified vol

    # Map entry timestamps to indices
    ts_to_idx = {int(df.index[i].timestamp() * 1000): i for i in range(len(df))}

    tagged = []
    for t in trades:
        idx = ts_to_idx.get(t.entry_time)
        if idx is None:
            # Find nearest
            continue

        regime = {
            "above_sma200": bool(df["close"].iloc[idx] > sma200.iloc[idx]) if not np.isnan(sma200.iloc[idx]) else None,
            "above_sma50": bool(df["close"].iloc[idx] > sma50.iloc[idx]) if not np.isnan(sma50.iloc[idx]) else None,
            "adx": float(adx_data["adx"].iloc[idx]) if not np.isnan(adx_data["adx"].iloc[idx]) else None,
            "pdi": float(adx_data["pdi"].iloc[idx]) if not np.isnan(adx_data["pdi"].iloc[idx]) else None,
            "mdi": float(adx_data["mdi"].iloc[idx]) if not np.isnan(adx_data["mdi"].iloc[idx]) else None,
            "pdi_gt_mdi": bool(adx_data["pdi"].iloc[idx] > adx_data["mdi"].iloc[idx]) if not (np.isnan(adx_data["pdi"].iloc[idx]) or np.isnan(adx_data["mdi"].iloc[idx])) else None,
        }
        t.regime = regime
        tagged.append(t)

    return tagged


def print_regime_analysis(trades, label=""):
    """Group trades by regime and show performance."""
    print(f"\n{'='*70}")
    print(f"  REGIME ANALYSIS {label}")
    print(f"{'='*70}")

    # Group by above/below SMA200
    above = [t for t in trades if t.regime.get("above_sma200") is True]
    below = [t for t in trades if t.regime.get("above_sma200") is False]

    for name, subset in [("ABOVE SMA200", above), ("BELOW SMA200", below)]:
        if not subset:
            print(f"\n  {name}: 0 trades")
            continue
        pnls = [t.pnl_pct for t in subset]
        wins = [p for p in pnls if p > 0]
        exits = Counter(t.exit_reason for t in subset)
        print(f"\n  {name}:")
        print(f"    Trades: {len(subset)}, Sum: {sum(pnls):+.1f}%, Avg: {np.mean(pnls):+.3f}%")
        print(f"    Win rate: {len(wins)/len(subset)*100:.1f}%")
        print(f"    Exits: {dict(exits)}")

    # Group by ADX strength
    strong_trend = [t for t in trades if t.regime.get("adx") is not None and t.regime["adx"] > 25]
    weak_trend = [t for t in trades if t.regime.get("adx") is not None and t.regime["adx"] <= 25]

    for name, subset in [("ADX > 25 (strong trend)", strong_trend), ("ADX <= 25 (weak trend)", weak_trend)]:
        if not subset:
            print(f"\n  {name}: 0 trades")
            continue
        pnls = [t.pnl_pct for t in subset]
        wins = [p for p in pnls if p > 0]
        print(f"\n  {name}:")
        print(f"    Trades: {len(subset)}, Sum: {sum(pnls):+.1f}%, Avg: {np.mean(pnls):+.3f}%")
        print(f"    Win rate: {len(wins)/len(subset)*100:.1f}%")

    # Group by PDI > MDI (bullish direction)
    bull_dir = [t for t in trades if t.regime.get("pdi_gt_mdi") is True]
    bear_dir = [t for t in trades if t.regime.get("pdi_gt_mdi") is False]

    for name, subset in [("PDI > MDI (bullish direction)", bull_dir), ("PDI <= MDI (bearish direction)", bear_dir)]:
        if not subset:
            print(f"\n  {name}: 0 trades")
            continue
        pnls = [t.pnl_pct for t in subset]
        wins = [p for p in pnls if p > 0]
        print(f"\n  {name}:")
        print(f"    Trades: {len(subset)}, Sum: {sum(pnls):+.1f}%, Avg: {np.mean(pnls):+.3f}%")
        print(f"    Win rate: {len(wins)/len(subset)*100:.1f}%")

    # Combined: below SMA200 + bearish direction
    toxic = [t for t in trades if t.regime.get("above_sma200") is False and t.regime.get("pdi_gt_mdi") is False]
    if toxic:
        pnls = [t.pnl_pct for t in toxic]
        print(f"\n  TOXIC (below SMA200 + PDI<MDI):")
        print(f"    Trades: {len(toxic)}, Sum: {sum(pnls):+.1f}%, Avg: {np.mean(pnls):+.3f}%")
        print(f"    Win rate: {len([p for p in pnls if p > 0])/len(toxic)*100:.1f}%")


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def walk_forward(df, strategy_cls, strategy_params, n_splits=6, label=""):
    """Run walk-forward validation."""
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD VALIDATION: {label} ({n_splits} splits)")
    print(f"{'='*70}")

    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()

        if len(split_df) < strategy_cls.min_bars + 50:
            print(f"  Split {s+1}: too small ({len(split_df)} bars), skipping")
            continue

        strategy = strategy_cls(strategy_params)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            split_df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params.get("stop_pct", 3.0),
            take_profit_pct=strategy.params.get("target_pct", 1.5),
            max_hold_bars=strategy.params.get("hold_hours", 6),
        )

        trades = result.trades
        n_trades = len(trades)
        lin_sum = sum(t.pnl_pct for t in trades)
        sharpe = result.metrics.sharpe_ratio

        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "⭐" if lin_sum > 0 else "  "

        print(f"  {star} {start_date}→{end_date}  trades={n_trades:>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}")
        results.append({"split": s+1, "sum": lin_sum, "sharpe": sharpe, "trades": n_trades})

    profitable = sum(1 for r in results if r["sum"] > 0)
    total = len(results)
    print(f"\n  → {profitable}/{total} OOS profitable")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_result_summary(result, label=""):
    """Compact result summary."""
    m = result.metrics
    trades = result.trades
    exits = Counter(t.exit_reason for t in trades)
    lin_sum = sum(t.pnl_pct for t in trades)

    print(f"\n  [{label}]")
    print(f"    Trades: {m.total_trades}, Linear sum: {lin_sum:+.1f}%")
    print(f"    Sharpe: {m.sharpe_ratio:.2f}, Sortino: {m.sortino_ratio:.2f}")
    print(f"    Max DD: {m.max_drawdown_pct:.1f}%, Win rate: {m.win_rate_pct:.1f}%")
    print(f"    PF: {m.profit_factor:.2f}, Avg win: {m.avg_win_pct:+.3f}%, Avg loss: {m.avg_loss_pct:+.3f}%")
    print(f"    Exits: {dict(exits)}")


def run_cooldown_backtest(df, strategy_cls, strategy_params, cooldown_bars=12, max_consecutive_stops=2):
    """Run backtest with consecutive-loss cooldown logic."""
    # Generate signals
    strategy = strategy_cls(strategy_params)
    signals = strategy.generate_signal(df)

    # Custom simulation with cooldown
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    # First run without cooldown to get baseline
    result_no_cooldown = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=strategy.params.get("stop_pct", 3.0),
        take_profit_pct=strategy.params.get("target_pct", 1.5),
        max_hold_bars=strategy.params.get("hold_hours", 6),
    )

    # Now manually simulate with cooldown
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    stop_pct = strategy.params.get("stop_pct", 3.0)
    target_pct = strategy.params.get("target_pct", 1.5)
    hold_bars = strategy.params.get("hold_hours", 6)
    slippage = 0.0005

    trades = []
    position = None
    consecutive_stops = 0
    cooldown_until = 0
    trade_id = 0

    n = len(df)
    for i in range(n):
        # Check cooldown
        if i < cooldown_until:
            continue

        if position is None:
            sig = int(signals.iloc[i]) if i < len(signals) else 0
            if sig == 1:
                entry_price = opens[i] if i + 1 < n else closes[i]
                entry_idx = i if i + 1 >= n else i + 1
                position = {
                    "entry_price": opens[entry_idx],
                    "entry_idx": entry_idx,
                    "stop_price": opens[entry_idx] * (1 - stop_pct / 100),
                    "target_price": opens[entry_idx] * (1 + target_pct / 100),
                }

        if position is not None:
            exit_price = None
            exit_reason = ""
            exit_idx = i

            # Check from entry_idx+1 to current
            for j in range(max(position["entry_idx"] + 1, i), i + 1):
                if j >= n:
                    break
                # Stop loss (using lows)
                if lows[j] <= position["stop_price"]:
                    exit_price = position["stop_price"] * (1 - slippage)
                    exit_reason = "stop_loss"
                    exit_idx = j
                    break
                # Take profit (using highs)
                if highs[j] >= position["target_price"]:
                    exit_price = position["target_price"] * (1 - slippage)
                    exit_reason = "take_profit"
                    exit_idx = j
                    break
                # Time exit
                if (j - position["entry_idx"]) >= hold_bars:
                    exit_price = opens[j] * (1 - slippage)
                    exit_reason = "time_exit"
                    exit_idx = j
                    break

            if exit_reason:
                trade_id += 1
                pnl = (exit_price / position["entry_price"] - 1) * 100
                trades.append({
                    "id": trade_id,
                    "pnl_pct": round(pnl, 4),
                    "exit_reason": exit_reason,
                    "exit_idx": exit_idx,
                })

                # Track consecutive stops for cooldown
                if exit_reason == "stop_loss":
                    consecutive_stops += 1
                    if consecutive_stops >= max_consecutive_stops:
                        cooldown_until = exit_idx + cooldown_bars
                        consecutive_stops = 0
                else:
                    consecutive_stops = 0

                position = None

    # Summary
    pnls = [t["pnl_pct"] for t in trades]
    exits = Counter(t["exit_reason"] for t in trades)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    print(f"\n  [Spring_SMA200 + Cooldown({cooldown_bars}h after {max_consecutive_stops} stops)]")
    print(f"    Trades: {len(trades)}, Linear sum: {sum(pnls):+.1f}%")
    print(f"    Win rate: {len(wins)/len(trades)*100:.1f}%" if trades else "    Win rate: N/A")
    if wins:
        print(f"    Avg win: {np.mean(wins):+.3f}%")
    if losses:
        print(f"    Avg loss: {np.mean(losses):+.3f}%")
    print(f"    Exits: {dict(exits)}")
    print(f"    Cooldown triggered: {sum(1 for t in trades if t['exit_reason'] == 'stop_loss') // max_consecutive_stops} times (approx)")

    return trades


def main():
    print("=" * 70)
    print("  SPRING REVERSAL — SMA200 FILTER RESEARCH")
    print("  Research: Does trend filter fix bear-market weakness?")
    print("=" * 70)

    # Load data
    store = OHLCVStore(db_path="data/cryptoquant.db")

    print("\n[1] Loading BTC/USDT 1h data...")
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    print(f"  OKX: {len(df_okx)} bars ({df_okx.index[0]} → {df_okx.index[-1]})")
    print(f"  Binance: {len(df_binance)} bars ({df_binance.index[0]} → {df_binance.index[-1]})")

    # Use OKX as primary
    df = df_okx

    # -----------------------------------------------------------------------
    # Part 1: Baseline confirmation
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 1: BASELINE CONFIRMATION")
    print("=" * 70)

    engine = BacktestEngine(commission=0.0005, slippage=0.0005)

    strategy = SpringBaseline()
    result = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=3.0, take_profit_pct=1.5, max_hold_bars=6,
    )
    print_result_summary(result, "Spring Baseline (OKX)")

    # -----------------------------------------------------------------------
    # Part 2: SMA filter variants
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 2: SMA/EMA FILTER VARIANTS")
    print("=" * 70)

    variants = [
        (SpringSMA200, {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}, "SMA200"),
        (SpringSMA150, {"lookback": 30, "sma_period": 150, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}, "SMA150"),
        (SpringEMA50, {"lookback": 30, "ema_period": 50, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}, "EMA50"),
    ]

    for cls, params, label in variants:
        strategy = cls(params)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params["stop_pct"],
            take_profit_pct=params["target_pct"],
            max_hold_bars=params["hold_hours"],
        )
        print_result_summary(result, f"Spring + {label}")

    # -----------------------------------------------------------------------
    # Part 3: Regime Analysis (baseline)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 3: REGIME ANALYSIS")
    print("=" * 70)

    strategy = SpringBaseline()
    result = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=3.0, take_profit_pct=1.5, max_hold_bars=6,
    )
    tagged = tag_trade_regimes(result.trades, df)
    print_regime_analysis(tagged, "— Spring Baseline")

    # Also do regime analysis for SMA200 variant
    strategy_sma = SpringSMA200({"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6})
    result_sma = engine.run(
        df, strategy_sma, symbol="BTC/USDT",
        stop_loss_pct=3.0, take_profit_pct=1.5, max_hold_bars=6,
    )
    tagged_sma = tag_trade_regimes(result_sma.trades, df)
    print_regime_analysis(tagged_sma, "— Spring + SMA200")

    # -----------------------------------------------------------------------
    # Part 4: Walk-Forward Validation
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 4: WALK-FORWARD VALIDATION")
    print("=" * 70)

    # Baseline WF
    wf_baseline = walk_forward(
        df, SpringBaseline,
        {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        n_splits=6, label="Spring Baseline"
    )

    # SMA200 WF
    wf_sma200 = walk_forward(
        df, SpringSMA200,
        {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        n_splits=6, label="Spring + SMA200"
    )

    # SMA150 WF
    wf_sma150 = walk_forward(
        df, SpringSMA150,
        {"lookback": 30, "sma_period": 150, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        n_splits=6, label="Spring + SMA150"
    )

    # -----------------------------------------------------------------------
    # Part 5: Cooldown mechanism
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 5: COOLDOWN MECHANISM (SMA200 + consecutive-loss pause)")
    print("=" * 70)

    cooldown_trades = run_cooldown_backtest(
        df, SpringSMA200,
        {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        cooldown_bars=12, max_consecutive_stops=2,
    )

    # Also test without SMA200 + cooldown
    print("\n  --- For comparison: Baseline + Cooldown ---")
    cooldown_baseline = run_cooldown_backtest(
        df, SpringBaseline,
        {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        cooldown_bars=12, max_consecutive_stops=2,
    )

    # -----------------------------------------------------------------------
    # Part 6: Binance cross-validation
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 6: BINANCE CROSS-VALIDATION")
    print("=" * 70)

    if len(df_binance) > 300:
        strategy = SpringBaseline()
        result = engine.run(
            df_binance, strategy, symbol="BTC/USDT",
            stop_loss_pct=3.0, take_profit_pct=1.5, max_hold_bars=6,
        )
        print_result_summary(result, "Spring Baseline (Binance)")

        strategy_sma = SpringSMA200({"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6})
        result_sma = engine.run(
            df_binance, strategy_sma, symbol="BTC/USDT",
            stop_loss_pct=3.0, take_profit_pct=1.5, max_hold_bars=6,
        )
        print_result_summary(result_sma, "Spring + SMA200 (Binance)")
    else:
        print("  Binance data insufficient for cross-validation")

    # -----------------------------------------------------------------------
    # Part 7: Target sweep with SMA200
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 7: TARGET SWEEP (SMA200 filter, targets 1.0-3.0%)")
    print("=" * 70)

    for target in [1.0, 1.2, 1.5, 2.0, 2.5, 3.0]:
        strategy_sma = SpringSMA200({"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": target, "hold_hours": 6})
        result_sma = engine.run(
            df, strategy_sma, symbol="BTC/USDT",
            stop_loss_pct=3.0, take_profit_pct=target, max_hold_bars=6,
        )
        m = result_sma.metrics
        print(f"  target={target:.1f}%  trades={m.total_trades:>4}  sharpe={m.sharpe_ratio:>6.2f}  "
              f"DD={m.max_drawdown_pct:>5.1f}%  WR={m.win_rate_pct:>5.1f}%  PF={m.profit_factor:.2f}  "
              f"sum={sum(t.pnl_pct for t in result_sma.trades):>+7.1f}%")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  RESEARCH SUMMARY")
    print("=" * 70)
    print("""
    Key questions answered:
    1. Does SMA200 filter improve Spring Sharpe?
    2. Does it fix the 2022 bear market split?
    3. Which SMA period works best (150 vs 200)?
    4. Does cooldown add value on top of SMA200?
    5. What's the optimal target with SMA200 filter?
    6. Does it hold up on Binance data?
    """)


if __name__ == "__main__":
    main()
