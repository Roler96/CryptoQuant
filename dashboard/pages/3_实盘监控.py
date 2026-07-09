"""Live / paper trading monitor — reads TradeJournal JSONL logs."""
import sys
from pathlib import Path

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
for _p in (_DASHBOARD_DIR.parent, _DASHBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import list_trade_journals, load_journal, strategy_name_from_journal_path

st.set_page_config(page_title="实盘监控 · CryptoQuant", page_icon="🛰️", layout="wide")
st.title("🛰️ 实盘 / 模拟交易监控")

journals = list_trade_journals()

if not journals:
    st.info(
        "logs/ 目录下暂无交易日志（trade_journal_*.jsonl）。\n\n"
        "运行 `uv run python live_runner.py` 启动实盘/模拟交易后，本页会自动显示交易记录与统计数据。"
    )
    st.stop()

strategy_names = [strategy_name_from_journal_path(p) for p in journals]
selected = st.selectbox("选择策略日志", strategy_names)

journal = load_journal(selected)
trades = journal.load_all()
stats = journal.stats()

if not trades:
    st.info("该日志文件暂无交易记录。")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("总交易笔数", stats["total"])
c2.metric("胜率", f"{stats['win_rate']:.1f}%")
c3.metric("累计盈亏(%)", f"{stats['total_pnl_pct']:+.2f}%")
c4.metric("累计盈亏(USDT)", f"{stats['total_pnl_abs']:+.2f}")
c5.metric("平均盈利 / 亏损(%)", f"{stats['avg_win']:+.2f} / {stats['avg_loss']:+.2f}")

st.divider()

trades_df = pd.DataFrame(trades)
trades_df["recorded_at"] = pd.to_datetime(trades_df["recorded_at"])
trades_df = trades_df.sort_values("recorded_at")
trades_df["cum_pnl_pct"] = trades_df.get("pnl_pct", 0).cumsum()

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=trades_df["recorded_at"], y=trades_df["cum_pnl_pct"], name="累计盈亏(%)",
    line=dict(color="#26a69a"), fill="tozeroy",
))
fig.update_layout(title="累计盈亏曲线 (%)", height=350, margin=dict(l=10, r=10, t=40, b=10))
st.plotly_chart(fig, use_container_width=True)

st.subheader(f"最近交易 ({len(trades_df)} 笔)")
display_cols = [c for c in [
    "recorded_at", "symbol", "side", "entry_price", "exit_price",
    "exit_reason", "pnl_pct", "pnl_abs", "hold_hours",
] if c in trades_df.columns]
st.dataframe(
    trades_df[display_cols].sort_values("recorded_at", ascending=False),
    use_container_width=True, hide_index=True,
)
