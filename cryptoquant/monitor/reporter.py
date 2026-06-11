"""PnL reporting — daily/weekly summaries."""
from cryptoquant.risk.manager import RiskManager


class Reporter:
    """Daily/weekly PnL summary generator."""

    def __init__(self, risk_manager: RiskManager, journal):
        self.risk_manager = risk_manager
        self.journal = journal

    def daily_summary(self) -> str:
        stats = self.risk_manager.get_daily_stats()

        lines = [
            "--- Daily Trading Summary ---",
            f"  Date:       {stats.date}",
            f"  Trades:     {stats.total_trades}",
            f"  Win Rate:   {stats.win_rate:.1f}%",
            f"  PnL (%):    {stats.total_pnl_pct:+.2f}%",
            f"  PnL (USDT): {stats.total_pnl_abs:+.2f}",
            f"  Balance:    {stats.current_balance:.2f} USDT",
            f"  Max DD:     {stats.max_drawdown_pct:.2f}%",
            "-------------------------------",
        ]

        if self.risk_manager.is_emergency_stop():
            lines.append("  WARNING: EMERGENCY STOP ACTIVE")

        return "\n".join(lines)

    def weekly_summary(self) -> str:
        all_trades = self.journal.load_all()
        if not all_trades:
            return "No trades this week."

        from collections import defaultdict

        by_day = defaultdict(list)
        for t in all_trades:
            day = t.get("recorded_at", "")[:10]
            by_day[day].append(t)

        lines = ["--- Weekly Trading Summary ---"]
        total_pnl = 0
        for day in sorted(by_day.keys())[-7:]:
            day_trades = by_day[day]
            day_pnl = sum(t.get("pnl_pct", 0) for t in day_trades)
            total_pnl += day_pnl
            lines.append(f"  {day}: {len(day_trades):2d} trades, PnL {day_pnl:+.2f}%")
        lines.append("  -------------------------")
        lines.append(f"  Week PnL: {total_pnl:+.2f}%")
        lines.append("-----------------------------")
        return "\n".join(lines)
