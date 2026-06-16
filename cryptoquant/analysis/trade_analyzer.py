"""Trade analyzer for performance and risk metrics."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TradeRecord:
    """Minimal trade record for analysis."""

    pnl_pct: float
    entry_time: int
    exit_time: int


class TradeAnalyzer:
    """Analyze a list of trades and compute performance metrics."""

    def __init__(self, trades: list[TradeRecord]):
        self.trades = trades
        self.pnls = np.array([t.pnl_pct for t in trades])

    def win_rate(self) -> float:
        """Percentage of winning trades."""
        if len(self.pnls) == 0:
            return 0.0
        return float(np.mean(self.pnls > 0) * 100)

    def profit_factor(self) -> float:
        """Gross profits / gross losses."""
        wins = self.pnls[self.pnls > 0]
        losses = self.pnls[self.pnls < 0]
        gross_wins = float(np.sum(wins)) if len(wins) > 0 else 0.0
        gross_losses = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
        if gross_losses == 0:
            return float("inf") if gross_wins > 0 else 0.0
        return gross_wins / gross_losses

    def sharpe(self, risk_free_rate: float = 0.0) -> float:
        """Sharpe ratio from trade returns (assumed independent)."""
        if len(self.pnls) < 2:
            return 0.0
        excess = self.pnls - risk_free_rate
        std = float(np.std(excess, ddof=1))
        if std == 0:
            return 0.0
        return float(np.mean(excess)) / std

    def sortino(self, risk_free_rate: float = 0.0) -> float:
        """Sortino ratio using downside deviation."""
        if len(self.pnls) < 2:
            return 0.0
        excess = self.pnls - risk_free_rate
        downside = excess[excess < 0]
        downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
        if downside_std == 0:
            return 0.0
        return float(np.mean(excess)) / downside_std

    def max_drawdown_pct(self) -> float:
        """Maximum drawdown from cumulative trade PnL curve."""
        if len(self.pnls) == 0:
            return 0.0
        cumulative = np.cumsum(self.pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = cumulative - running_max
        min_dd = float(np.min(drawdowns))
        return abs(min_dd)

    def cvar(self, alpha: float = 0.05) -> float:
        """Conditional Value at Risk (average of worst alpha% returns)."""
        if len(self.pnls) == 0:
            return 0.0
        sorted_pnls = np.sort(self.pnls)
        cutoff = max(1, int(np.ceil(alpha * len(sorted_pnls))))
        worst = sorted_pnls[:cutoff]
        return float(np.mean(worst))

    def streaks(self) -> dict[str, int]:
        """Longest consecutive win and loss streaks."""
        if len(self.pnls) == 0:
            return {"win_streak": 0, "loss_streak": 0}
        signs = np.sign(self.pnls)
        max_win = 0
        max_loss = 0
        current_win = 0
        current_loss = 0
        for s in signs:
            if s > 0:
                current_win += 1
                current_loss = 0
                max_win = max(max_win, current_win)
            elif s < 0:
                current_loss += 1
                current_win = 0
                max_loss = max(max_loss, current_loss)
            else:
                current_win = 0
                current_loss = 0
        return {"win_streak": max_win, "loss_streak": max_loss}

    def trade_distribution(self, bins: int = 10) -> dict[str, np.ndarray]:
        """Histogram of trade PnL distribution."""
        if len(self.pnls) == 0:
            return {"counts": np.array([]), "edges": np.array([])}
        counts, edges = np.histogram(self.pnls, bins=bins)
        return {"counts": counts, "edges": edges}

    def equity_curve(self) -> pd.Series:
        """Cumulative equity curve from trade PnLs."""
        if len(self.trades) == 0:
            return pd.Series(dtype=float)
        times = [t.exit_time for t in self.trades]
        cumulative = np.cumsum(self.pnls)
        return pd.Series(cumulative, index=times)
