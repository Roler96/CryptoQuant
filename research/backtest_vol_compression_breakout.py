"""
Volatility Compression Breakout (VCB) — Research Backtest
==========================================================

Hypothesis: After periods of abnormally low volatility (BB width compression),
price breaks out directionally with volume expansion. The breakout tends to
continue, producing a tradeable move.

This is a TREND-FOLLOWING strategy — the opposite of the mean-reversion
approaches (Wick, Spring) that failed. If it works, it complements them.

Signal Logic:
1. Compute Bollinger Band width (upper - lower) / middle
2. Detect compression: BB width < 20th percentile of its 100-bar history
3. Detect breakout: close > upper_band (long) or close < lower_band (short)
4. Volume confirmation: breakout bar volume > 1.5× 20-bar avg volume
5. Entry: next bar open in breakout direction
6. Exit: ATR-based stop (2× ATR), ATR-based target (3× ATR), time exit (24h)

Research questions:
- Does VCB produce positive expectancy on BTC 1h?
- Which compression threshold works best?
- Does volume confirmation help?
- Does a trend filter (SMA200) improve results?
- Walk-forward validation: is it robust across time periods?
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import sma, ema, atr, bollinger_bands


# ---------------------------------------------------------------------------
# Signal functions
# ---------------------------------------------------------------------------

def vol_compression_breakout_signal(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    compression_pctile: float = 20.0,
    compression_lookback: int = 100,
    vol_ma_period: int = 20,
    vol_multiplier: float = 1.5,
    require_volume: bool = True,
    trend_filter: str = "none",   # "none", "sma200", "ema50"
    trend_period: int = 200,
) -> pd.Series:
    """
    Volatility Compression Breakout signal.
    
    Returns: 1 for long breakout, -1 for short breakout, 0 for no signal.
    """
    close = df["close"]
    volume = df["volume"]
    
    # 1. Bollinger Bands
    bb = bollinger_bands(df, period=bb_period, std=bb_std)
    bb_width = bb["width"]
    
    # 2. Compression detection: BB width below percentile threshold
    pctile_threshold = bb_width.rolling(compression_lookback).quantile(compression_pctile / 100)
    is_compressed = bb_width < pctile_threshold
    
    # 3. Breakout detection
    breakout_long = close > bb["upper"]
    breakout_short = close < bb["lower"]
    
    # 4. Volume confirmation
    vol_avg = volume.rolling(vol_ma_period).mean()
    vol_surge = volume > (vol_avg * vol_multiplier)
    
    if require_volume:
        long_signal = is_compressed & breakout_long & vol_surge
        short_signal = is_compressed & breakout_short & vol_surge
    else:
        long_signal = is_compressed & breakout_long
        short_signal = is_compressed & breakout_short
    
    # 5. Trend filter (for long-only crypto, only take longs in uptrend)
    if trend_filter == "sma200":
        trend_val = sma(close, trend_period)
        above_trend = close > trend_val
        long_signal = long_signal & above_trend
        # Short signals only in downtrend
        short_signal = short_signal & (~above_trend)
    elif trend_filter == "ema50":
        trend_val = ema(close, trend_period)
        above_trend = close > trend_val
        long_signal = long_signal & above_trend
        short_signal = short_signal & (~above_trend)
    
    # Combine: +1 long, -1 short
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[long_signal] = 1
    signal[short_signal] = -1
    
    return signal


# ---------------------------------------------------------------------------
# Strategy classes
# ---------------------------------------------------------------------------

class VCBBaseline(Strategy):
    """Volatility Compression Breakout — baseline (long+short, no volume filter)."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20, "bb_std": 2.0,
        "compression_pctile": 20.0, "compression_lookback": 100,
        "vol_ma_period": 20, "vol_multiplier": 1.5,
        "require_volume": False,
        "trend_filter": "none",
        "stop_pct": 3.0, "target_pct": 4.5, "hold_hours": 24,
    }

    @property
    def name(self):
        return "VCB_Baseline"

    def generate_signal(self, df):
        df = self.preprocess(df)
        return vol_compression_breakout_signal(
            df,
            bb_period=self.params["bb_period"],
            bb_std=self.params["bb_std"],
            compression_pctile=self.params["compression_pctile"],
            compression_lookback=self.params["compression_lookback"],
            vol_ma_period=self.params["vol_ma_period"],
            vol_multiplier=self.params["vol_multiplier"],
            require_volume=self.params["require_volume"],
            trend_filter=self.params["trend_filter"],
        )


class VCBLongOnly(Strategy):
    """VCB — long only (no short signals)."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20, "bb_std": 2.0,
        "compression_pctile": 20.0, "compression_lookback": 100,
        "vol_ma_period": 20, "vol_multiplier": 1.5,
        "require_volume": False,
        "stop_pct": 3.0, "target_pct": 4.5, "hold_hours": 24,
    }

    @property
    def name(self):
        return "VCB_LongOnly"

    def generate_signal(self, df):
        df = self.preprocess(df)
        sig = vol_compression_breakout_signal(
            df,
            bb_period=self.params["bb_period"],
            bb_std=self.params["bb_std"],
            compression_pctile=self.params["compression_pctile"],
            compression_lookback=self.params["compression_lookback"],
            vol_ma_period=self.params["vol_ma_period"],
            vol_multiplier=self.params["vol_multiplier"],
            require_volume=self.params["require_volume"],
            trend_filter="none",
        )
        # Long only
        return sig.clip(lower=0)


class VCBVolConfirm(Strategy):
    """VCB — long only + volume confirmation."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20, "bb_std": 2.0,
        "compression_pctile": 20.0, "compression_lookback": 100,
        "vol_ma_period": 20, "vol_multiplier": 1.5,
        "stop_pct": 3.0, "target_pct": 4.5, "hold_hours": 24,
    }

    @property
    def name(self):
        return "VCB_VolConfirm"

    def generate_signal(self, df):
        df = self.preprocess(df)
        sig = vol_compression_breakout_signal(
            df,
            bb_period=self.params["bb_period"],
            bb_std=self.params["bb_std"],
            compression_pctile=self.params["compression_pctile"],
            compression_lookback=self.params["compression_lookback"],
            vol_ma_period=self.params["vol_ma_period"],
            vol_multiplier=self.params["vol_multiplier"],
            require_volume=True,
            trend_filter="none",
        )
        return sig.clip(lower=0)


class VCBSMA200(Strategy):
    """VCB — long only + SMA200 trend filter."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20, "bb_std": 2.0,
        "compression_pctile": 20.0, "compression_lookback": 100,
        "vol_ma_period": 20, "vol_multiplier": 1.5,
        "require_volume": False,
        "trend_filter": "sma200", "trend_period": 200,
        "stop_pct": 3.0, "target_pct": 4.5, "hold_hours": 24,
    }

    @property
    def name(self):
        return "VCB_SMA200"

    def generate_signal(self, df):
        df = self.preprocess(df)
        sig = vol_compression_breakout_signal(
            df,
            bb_period=self.params["bb_period"],
            bb_std=self.params["bb_std"],
            compression_pctile=self.params["compression_pctile"],
            compression_lookback=self.params["compression_lookback"],
            vol_ma_period=self.params["vol_ma_period"],
            vol_multiplier=self.params["vol_multiplier"],
            require_volume=self.params["require_volume"],
            trend_filter=self.params["trend_filter"],
            trend_period=self.params["trend_period"],
        )
        return sig.clip(lower=0)


class VCBVolSMA(Strategy):
    """VCB — long only + volume + SMA200 (kitchen sink)."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 20, "bb_std": 2.0,
        "compression_pctile": 20.0, "compression_lookback": 100,
        "vol_ma_period": 20, "vol_multiplier": 1.5,
        "trend_filter": "sma200", "trend_period": 200,
        "stop_pct": 3.0, "target_pct": 4.5, "hold_hours": 24,
    }

    @property
    def name(self):
        return "VCB_Vol_SMA200"

    def generate_signal(self, df):
        df = self.preprocess(df)
        sig = vol_compression_breakout_signal(
            df,
            bb_period=self.params["bb_period"],
            bb_std=self.params["bb_std"],
            compression_pctile=self.params["compression_pctile"],
            compression_lookback=self.params["compression_lookback"],
            vol_ma_period=self.params["vol_ma_period"],
            vol_multiplier=self.params["vol_multiplier"],
            require_volume=True,
            trend_filter=self.params["trend_filter"],
            trend_period=self.params["trend_period"],
        )
        return sig.clip(lower=0)


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def walk_forward(df, strategy_cls, strategy_params, n_splits=6, label=""):
    """Run walk-forward validation."""
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD: {label} ({n_splits} splits)")
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
            take_profit_pct=strategy.params.get("target_pct", 4.5),
            max_hold_bars=strategy.params.get("hold_hours", 24),
        )

        trades = result.trades
        n_trades = len(trades)
        lin_sum = sum(t.pnl_pct for t in trades)
        sharpe = result.metrics.sharpe_ratio
        max_dd = result.metrics.max_drawdown_pct

        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "⭐" if lin_sum > 0 else "  "

        print(f"  {star} {start_date}→{end_date}  trades={n_trades:>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}  DD={max_dd:.1f}%")
        results.append({"split": s+1, "period": f"{start_date}→{end_date}", "sum": lin_sum, "sharpe": sharpe, "trades": n_trades, "dd": max_dd})

    profitable = sum(1 for r in results if r["sum"] > 0)
    total = len(results)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    print(f"\n  → {profitable}/{total} OOS profitable, mean Sharpe: {mean_sharpe:+.2f}")
    return results


# ---------------------------------------------------------------------------
# Target sweep
# ---------------------------------------------------------------------------

def target_sweep(df, strategy_cls, base_params, targets, label=""):
    """Sweep target_pct to find optimal."""
    print(f"\n{'='*70}")
    print(f"  TARGET SWEEP: {label}")
    print(f"{'='*70}")
    print(f"  {'Target':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*55}")
    
    best_sharpe = -999
    best_target = None
    
    for target in targets:
        params = {**base_params, "target_pct": target}
        strategy = strategy_cls(params)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params.get("stop_pct", 3.0),
            take_profit_pct=target,
            max_hold_bars=params.get("hold_hours", 24),
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {target:>7.1f}% {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        
        if m.sharpe_ratio > best_sharpe:
            best_sharpe = m.sharpe_ratio
            best_target = target
    
    print(f"\n  Best target: {best_target:.1f}% (Sharpe {best_sharpe:+.2f})")
    return best_target


# ---------------------------------------------------------------------------
# Stop sweep
# ---------------------------------------------------------------------------

def stop_sweep(df, strategy_cls, base_params, stops, label=""):
    """Sweep stop_pct to find optimal."""
    print(f"\n{'='*70}")
    print(f"  STOP SWEEP: {label}")
    print(f"{'='*70}")
    print(f"  {'Stop':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*55}")
    
    best_sharpe = -999
    best_stop = None
    
    for stop in stops:
        params = {**base_params, "stop_pct": stop}
        strategy = strategy_cls(params)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=stop,
            take_profit_pct=params.get("target_pct", 4.5),
            max_hold_bars=params.get("hold_hours", 24),
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {stop:>7.1f}% {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        
        if m.sharpe_ratio > best_sharpe:
            best_sharpe = m.sharpe_ratio
            best_stop = stop
    
    print(f"\n  Best stop: {best_stop:.1f}% (Sharpe {best_sharpe:+.2f})")
    return best_stop


# ---------------------------------------------------------------------------
# Hold time sweep
# ---------------------------------------------------------------------------

def hold_sweep(df, strategy_cls, base_params, holds, label=""):
    """Sweep hold_hours to find optimal."""
    print(f"\n{'='*70}")
    print(f"  HOLD TIME SWEEP: {label}")
    print(f"{'='*70}")
    print(f"  {'Hold':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*55}")
    
    best_sharpe = -999
    best_hold = None
    
    for hold in holds:
        params = {**base_params, "hold_hours": hold}
        strategy = strategy_cls(params)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params.get("stop_pct", 3.0),
            take_profit_pct=params.get("target_pct", 4.5),
            max_hold_bars=hold,
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {hold:>7}h {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        
        if m.sharpe_ratio > best_sharpe:
            best_sharpe = m.sharpe_ratio
            best_hold = hold
    
    print(f"\n  Best hold: {best_hold}h (Sharpe {best_sharpe:+.2f})")
    return best_hold


# ---------------------------------------------------------------------------
# Compression percentile sweep
# ---------------------------------------------------------------------------

def compression_sweep(df, strategy_cls, base_params, pctiles, label=""):
    """Sweep compression percentile threshold."""
    print(f"\n{'='*70}")
    print(f"  COMPRESSION PERCENTILE SWEEP: {label}")
    print(f"{'='*70}")
    print(f"  {'Pctile':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*55}")
    
    best_sharpe = -999
    best_pctile = None
    
    for pctile in pctiles:
        params = {**base_params, "compression_pctile": pctile}
        strategy = strategy_cls(params)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params.get("stop_pct", 3.0),
            take_profit_pct=params.get("target_pct", 4.5),
            max_hold_bars=params.get("hold_hours", 24),
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {pctile:>7.0f}% {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")
        
        if m.sharpe_ratio > best_sharpe:
            best_sharpe = m.sharpe_ratio
            best_pctile = pctile
    
    print(f"\n  Best compression pctile: {best_pctile:.0f}% (Sharpe {best_sharpe:+.2f})")
    return best_pctile


# ---------------------------------------------------------------------------
# Detailed result printer
# ---------------------------------------------------------------------------

def print_full_result(result, label=""):
    """Print complete backtest result."""
    m = result.metrics
    trades = result.trades
    exits = Counter(t.exit_reason for t in trades)
    lin_sum = sum(t.pnl_pct for t in trades)
    
    print(f"\n{'='*70}")
    print(f"  FULL BACKTEST: {label}")
    print(f"{'='*70}")
    print(f"  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {m.total_trades}")
    print(f"  Compound Return:    {m.total_return_pct:+.1f}%")
    print(f"  Linear Sum:         {lin_sum:+.1f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:.1f}%")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.3f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.3f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Volatility (ann):   {m.volatility_annual_pct:.1f}%")
    print(f"  VaR 95%:            {m.var_95_pct:+.2f}%")
    print(f"  CVaR 95%:           {m.cvar_95_pct:+.2f}%")
    
    # Exit breakdown
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse", "end_of_data"]:
        if reason in exits:
            subset = [t for t in trades if t.exit_reason == reason]
            avg_pnl = np.mean([t.pnl_pct for t in subset])
            total_pnl = sum(t.pnl_pct for t in subset)
            pct = len(subset) / len(trades) * 100
            print(f"    {reason:<16} {len(subset):>5} ({pct:>4.1f}%)  avg={avg_pnl:>+6.2f}%  total={total_pnl:>+8.1f}%")
    
    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for t in trades:
        if t.pnl_pct <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0
    print(f"\n  Max Consecutive Losses: {max_consec}")
    
    # MFE/MAE analysis
    mfes = [t.mfe_pct for t in trades]
    maes = [t.mae_pct for t in trades]
    print(f"\n  Max Favorable Excursion:  mean={np.mean(mfes):+.2f}%  median={np.median(mfes):+.2f}%")
    print(f"  Max Adverse Excursion:    mean={np.mean(maes):+.2f}%  median={np.median(maes):+.2f}%")
    
    # Time-exit analysis
    time_exits = [t for t in trades if t.exit_reason == "time_exit"]
    if time_exits:
        te_pnls = [t.pnl_pct for t in time_exits]
        te_wins = [p for p in te_pnls if p > 0]
        print(f"\n  Time-Exit Analysis:")
        print(f"    Count: {len(time_exits)} ({len(time_exits)/len(trades)*100:.1f}%)")
        print(f"    Avg PnL: {np.mean(te_pnls):+.3f}%")
        print(f"    Win rate: {len(te_wins)/len(time_exits)*100:.1f}%")
        print(f"    Sum: {sum(te_pnls):+.1f}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("  VOLATILITY COMPRESSION BREAKOUT — RESEARCH BACKTEST")
    print("  Direction: Trend-following via BB squeeze + breakout")
    print("  Data: OKX BTC/USDT 1h (2019-2026)")
    print("=" * 70)

    # Load data
    store = OHLCVStore(db_path="data/cryptoquant.db")

    print("\n[1] Loading BTC/USDT 1h data...")
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    print(f"  OKX: {len(df_okx)} bars ({df_okx.index[0]} → {df_okx.index[-1]})")
    print(f"  Binance: {len(df_binance)} bars ({df_binance.index[0]} → {df_binance.index[-1]})")

    df = df_okx

    # -----------------------------------------------------------------------
    # Part 1: Baseline variants
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 1: BASELINE VARIANTS")
    print("=" * 70)

    engine = BacktestEngine(commission=0.0005, slippage=0.0005)

    variants = [
        (VCBBaseline, None, "VCB Baseline (long+short, no vol filter)"),
        (VCBLongOnly, None, "VCB Long Only (no vol filter)"),
        (VCBVolConfirm, None, "VCB Long + Volume Confirmation"),
        (VCBSMA200, None, "VCB Long + SMA200 Trend Filter"),
        (VCBVolSMA, None, "VCB Long + Volume + SMA200"),
    ]

    for cls, params_override, label in variants:
        params = params_override or cls.DEFAULT_PARAMS.copy()
        strategy = cls(params)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params.get("stop_pct", 3.0),
            take_profit_pct=params.get("target_pct", 4.5),
            max_hold_bars=params.get("hold_hours", 24),
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        exits = Counter(t.exit_reason for t in result.trades)
        print(f"\n  [{label}]")
        print(f"    Trades: {m.total_trades}, Sum: {lin_sum:+.1f}%, Sharpe: {m.sharpe_ratio:+.2f}")
        print(f"    Max DD: {m.max_drawdown_pct:.1f}%, WR: {m.win_rate_pct:.1f}%, PF: {m.profit_factor:.2f}")
        print(f"    Exits: {dict(exits)}")

    # -----------------------------------------------------------------------
    # Part 2: Full detail on best baseline
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 2: DETAILED RESULTS — Best Variants")
    print("=" * 70)

    # Print full detail for VCB_VolConfirm and VCB_SMA200
    for cls, label in [(VCBVolConfirm, "VCB VolConfirm"), (VCBSMA200, "VCB SMA200"), (VCBVolSMA, "VCB Vol+SMA")]:
        params = cls.DEFAULT_PARAMS.copy()
        strategy = cls(params)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params.get("stop_pct", 3.0),
            take_profit_pct=params.get("target_pct", 4.5),
            max_hold_bars=params.get("hold_hours", 24),
        )
        print_full_result(result, label)

    # -----------------------------------------------------------------------
    # Part 3: Parameter sweeps on best variant
    # -----------------------------------------------------------------------
    # Determine which variant to optimize based on Part 1 results
    # Use VCBVolConfirm as the base for sweeps (volume confirmation is a good filter)
    print("\n" + "=" * 70)
    print("  PART 3: PARAMETER SWEEPS")
    print("=" * 70)

    base_params = VCBVolConfirm.DEFAULT_PARAMS.copy()
    
    # 3a: Target sweep
    best_target = target_sweep(df, VCBVolConfirm, base_params, 
                               [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.0, 8.0],
                               "VCB VolConfirm — Target")
    
    # 3b: Stop sweep
    best_stop = stop_sweep(df, VCBVolConfirm, base_params,
                           [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
                           "VCB VolConfirm — Stop")
    
    # 3c: Hold time sweep
    best_hold = hold_sweep(df, VCBVolConfirm, base_params,
                           [4, 6, 8, 12, 16, 24, 36, 48],
                           "VCB VolConfirm — Hold Time")
    
    # 3d: Compression percentile sweep
    best_pctile = compression_sweep(df, VCBVolConfirm, base_params,
                                    [5, 10, 15, 20, 25, 30, 40, 50],
                                    "VCB VolConfirm — Compression %ile")

    # -----------------------------------------------------------------------
    # Part 4: Optimized variant full backtest
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 4: OPTIMIZED VARIANT")
    print("=" * 70)

    opt_params = {
        **base_params,
        "target_pct": best_target,
        "stop_pct": best_stop,
        "hold_hours": best_hold,
        "compression_pctile": best_pctile,
    }
    
    print(f"\n  Optimized params: target={best_target}%, stop={best_stop}%, "
          f"hold={best_hold}h, compression_pctile={best_pctile}%")
    
    strategy = VCBVolConfirm(opt_params)
    result = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=best_stop,
        take_profit_pct=best_target,
        max_hold_bars=best_hold,
    )
    print_full_result(result, f"VCB VolConfirm OPTIMIZED")

    # Also test optimized on SMA200 variant
    print("\n  --- Also testing with SMA200 filter ---")
    opt_params_sma = {
        **opt_params,
        "trend_filter": "sma200",
        "trend_period": 200,
    }
    strategy_sma = VCBSMA200(opt_params_sma)
    result_sma = engine.run(
        df, strategy_sma, symbol="BTC/USDT",
        stop_loss_pct=best_stop,
        take_profit_pct=best_target,
        max_hold_bars=best_hold,
    )
    print_full_result(result_sma, "VCB SMA200 OPTIMIZED")

    # -----------------------------------------------------------------------
    # Part 5: Walk-forward validation
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 5: WALK-FORWARD VALIDATION")
    print("=" * 70)

    # Walk-forward on optimized VCBVolConfirm
    wf_results_1 = walk_forward(df, VCBVolConfirm, opt_params, label="VCB VolConfirm OPTIMIZED")
    
    # Walk-forward on optimized VCB SMA200
    wf_results_2 = walk_forward(df, VCBSMA200, opt_params_sma, label="VCB SMA200 OPTIMIZED")

    # Also walk-forward on baseline (no optimization) for comparison
    wf_results_3 = walk_forward(df, VCBVolConfirm, VCBVolConfirm.DEFAULT_PARAMS.copy(), 
                                label="VCB VolConfirm BASELINE")

    # -----------------------------------------------------------------------
    # Part 6: Binance cross-validation
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 6: BINANCE CROSS-VALIDATION")
    print("=" * 70)

    for params, label in [(opt_params, "Optimized"), (opt_params_sma, "Optimized+SMA")]:
        cls = VCBVolConfirm if "trend_filter" not in params or params.get("trend_filter") == "none" else VCBSMA200
        # For SMA variant, need to use the right class
        if params.get("trend_filter") == "sma200":
            cls = VCBSMA200
        else:
            cls = VCBVolConfirm
        
        strategy = cls(params)
        result = engine.run(
            df_binance, strategy, symbol="BTC/USDT",
            stop_loss_pct=params.get("stop_pct", 3.0),
            take_profit_pct=params.get("target_pct", 4.5),
            max_hold_bars=params.get("hold_hours", 24),
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"\n  [{label} — Binance]")
        print(f"    Trades: {m.total_trades}, Sum: {lin_sum:+.1f}%, Sharpe: {m.sharpe_ratio:+.2f}")
        print(f"    Max DD: {m.max_drawdown_pct:.1f}%, WR: {m.win_rate_pct:.1f}%, PF: {m.profit_factor:.2f}")

    # -----------------------------------------------------------------------
    # Part 7: Volume multiplier sensitivity
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  PART 7: VOLUME MULTIPLIER SENSITIVITY")
    print("=" * 70)
    print(f"  {'VolMult':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*55}")
    
    for vol_mult in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]:
        params = {**base_params, "vol_multiplier": vol_mult}
        strategy = VCBVolConfirm(params)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params.get("stop_pct", 3.0),
            take_profit_pct=params.get("target_pct", 4.5),
            max_hold_bars=params.get("hold_hours", 24),
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {vol_mult:>7.1f}x {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")

    print("\n" + "=" * 70)
    print("  RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
