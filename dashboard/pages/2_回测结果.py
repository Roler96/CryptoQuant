"""Run a backtest on demand and visualize the results."""
import sys
from pathlib import Path

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
for _p in (_DASHBOARD_DIR.parent, _DASHBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd
import streamlit as st

from charts import (
    drawdown_fig,
    equity_curve_fig,
    exit_reason_fig,
    mae_mfe_scatter_fig,
    monthly_returns_fig,
    pnl_histogram_fig,
    trades_on_price_fig,
)
from cryptoquant.analysis.trade_analyzer import TradeAnalyzer, TradeRecord
from cryptoquant.engine.backtest import generate_report
from utils import (
    data_fingerprint,
    discover_strategies,
    get_store,
    list_ohlcv_series,
    run_backtest_cached,
)

st.set_page_config(page_title="回测结果 · CryptoQuant", page_icon="🧪", layout="wide")
st.title("🧪 回测结果")

strategies = discover_strategies()
series = list_ohlcv_series()

if not strategies:
    st.warning("未在 strategies/ 目录发现任何策略。")
    st.stop()
if not series:
    st.warning("本地没有行情数据，请先到「行情数据」页面拉取历史数据。")
    st.stop()

with st.sidebar:
    st.subheader("回测配置")
    strategy_name = st.selectbox("策略", sorted(strategies.keys()))
    strategy_cls = strategies[strategy_name]

    series_labels = [f"{ex} · {sym} · {tf}" for ex, sym, tf in series]
    series_idx = st.selectbox("数据源", range(len(series)), format_func=lambda i: series_labels[i])
    exchange, symbol, timeframe = series[series_idx]

    data_range = get_store().get_range(exchange, symbol, timeframe)
    if data_range is not None:
        range_min = pd.to_datetime(data_range[0], unit="ms").date()
        range_max = pd.to_datetime(data_range[1], unit="ms").date()
        picked = st.date_input(
            "回测时间段",
            value=(range_min, range_max),
            min_value=range_min,
            max_value=range_max,
        )
        # date_input returns a 1-tuple while the user is mid-selection
        date_start = picked[0] if isinstance(picked, tuple) else picked
        date_end = picked[1] if isinstance(picked, tuple) and len(picked) == 2 else range_max
    else:
        date_start = date_end = None

    initial_capital = st.number_input("初始资金 (USDT)", min_value=100.0, value=10_000.0, step=100.0)
    commission_bps = st.number_input("单边手续费 (bps)", min_value=0.0, value=10.0, step=1.0)
    slippage_bps = st.number_input("单边滑点 (bps)", min_value=0.0, value=5.0, step=1.0)

    sizer_method = st.selectbox(
        "仓位模型",
        ["atr", "fixed"],
        format_func=lambda m: {"atr": "ATR 波动率调仓（实盘/脚本同款）", "fixed": "固定比例"}[m],
    )
    if sizer_method == "fixed":
        risk_pct = st.slider("单笔仓位占比 (%)", min_value=1, max_value=100, value=100)
        sizer_config = {"method": "fixed", "risk_pct": float(risk_pct)}
    else:
        base_risk_pct = st.number_input("基础仓位 (%)", min_value=1.0, max_value=100.0, value=10.0, step=1.0)
        atr_mult = st.number_input("ATR 系数", min_value=0.1, value=1.0, step=0.1)
        sizer_config = {
            "method": "atr", "base_risk_pct": float(base_risk_pct),
            "atr_period": 14, "multiplier": float(atr_mult),
        }

    st.divider()
    st.subheader("策略参数")
    param_overrides = {}
    for key, default in getattr(strategy_cls, "DEFAULT_PARAMS", {}).items():
        if isinstance(default, bool):
            param_overrides[key] = st.checkbox(key, value=default)
        elif isinstance(default, int):
            param_overrides[key] = st.number_input(key, value=default, step=1)
        elif isinstance(default, float):
            param_overrides[key] = st.number_input(key, value=default)
        else:
            param_overrides[key] = st.text_input(key, value=str(default))

    run_clicked = st.button("运行回测", type="primary", use_container_width=True)

if run_clicked:
    st.session_state["bt_config"] = {
        "strategy_name": strategy_name,
        "source": (exchange, symbol, timeframe),
        "date_range": (str(date_start), str(date_end)) if date_start else None,
        "params": dict(param_overrides),
        "engine_kwargs": {
            "initial_capital": initial_capital,
            "commission": commission_bps / 10_000,
            "slippage": slippage_bps / 10_000,
        },
        "sizer": sizer_config,
    }

cfg = st.session_state.get("bt_config")
if cfg is None:
    st.info("在左侧选择策略与数据源，点击「运行回测」。")
    st.stop()

exchange, symbol, timeframe = cfg["source"]
store = get_store()
start_ms = end_ms = None
if cfg.get("date_range"):
    d0, d1 = cfg["date_range"]
    start_ms = int(pd.Timestamp(d0).timestamp() * 1000)
    end_ms = int((pd.Timestamp(d1) + pd.Timedelta(days=1)).timestamp() * 1000) - 1
df = store.load(exchange, symbol, timeframe, start=start_ms, end=end_ms)
if df.empty:
    st.error("所选时间段内没有本地数据。")
    st.stop()

with st.spinner("回测运行中..."):
    try:
        result = run_backtest_cached(
            df,
            data_fingerprint(exchange, symbol, timeframe, df),
            cfg["strategy_name"],
            tuple(sorted(cfg["params"].items())),
            tuple(sorted(cfg["engine_kwargs"].items())),
            tuple(sorted(cfg["sizer"].items())),
        )
    except Exception as e:
        st.error(f"回测失败: {e}")
        st.stop()

st.caption(
    f"策略 **{result.strategy_name}** · {symbol} · {timeframe} · "
    f"{pd.to_datetime(result.start_time, unit='ms'):%Y-%m-%d} ~ "
    f"{pd.to_datetime(result.end_time, unit='ms'):%Y-%m-%d} · 参数 {cfg['params']}"
)

m = result.metrics
trades = result.trades

tab_overview, tab_trades, tab_risk, tab_detail = st.tabs(["概览", "交易分析", "风险", "明细"])

with tab_overview:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总收益率", f"{m.total_return_pct:+.2f}%")
    c2.metric("年化收益率", f"{m.annualized_return_pct:+.2f}%")
    c3.metric("夏普比率", f"{m.sharpe_ratio:.2f}")
    c4.metric("最大回撤", f"{m.max_drawdown_pct:.2f}%")
    c5.metric("胜率", f"{m.win_rate_pct:.1f}%")

    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("总交易笔数", m.total_trades)
    c7.metric("盈亏比 (Profit Factor)", f"{m.profit_factor:.2f}")
    c8.metric("平均持仓时长(h)", f"{m.avg_hold_hours:.1f}")
    c9.metric("Sortino", f"{m.sortino_ratio:.2f}")
    c10.metric("最终权益", f"{result.final_equity:,.2f}")

    st.plotly_chart(equity_curve_fig(result.equity_curve), use_container_width=True)
    st.plotly_chart(drawdown_fig(result.drawdown_curve), use_container_width=True)
    if m.monthly_returns is not None and len(m.monthly_returns) > 0:
        st.plotly_chart(monthly_returns_fig(m.monthly_returns * 100), use_container_width=True)

with tab_trades:
    if not trades:
        st.info("回测期间没有产生任何交易。")
    else:
        st.plotly_chart(trades_on_price_fig(df, trades, title=f"{symbol} 开平仓位置"), use_container_width=True)
        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(pnl_histogram_fig(trades), use_container_width=True)
        with col_r:
            st.plotly_chart(exit_reason_fig(trades), use_container_width=True)
        st.plotly_chart(mae_mfe_scatter_fig(trades), use_container_width=True)
        st.caption(
            "MAE（最大不利偏移）：交易过程中浮亏最深处。若大量盈利单的 MAE 很小，"
            "说明可以收紧止损；若亏损单 MAE 与最终亏损接近，说明止损基本没有救回空间。"
        )

with tab_risk:
    analyzer = TradeAnalyzer([
        TradeRecord(pnl_pct=t.pnl_pct, entry_time=t.entry_time, exit_time=t.exit_time)
        for t in trades
    ])
    streaks = analyzer.streaks() if trades else {"win_streak": 0, "loss_streak": 0}

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("VaR 95% (日)", f"{m.var_95_pct:.2f}%")
    r2.metric("CVaR 95% (日)", f"{m.cvar_95_pct:.2f}%")
    r3.metric("年化波动率", f"{m.volatility_annual_pct:.2f}%")
    r4.metric("最大回撤持续", f"{m.max_drawdown_days} 天")

    r5, r6, r7, r8 = st.columns(4)
    r5.metric("最长连胜", streaks["win_streak"])
    r6.metric("最长连败", streaks["loss_streak"])
    r7.metric("平均盈利", f"{m.avg_win_pct:+.2f}%")
    r8.metric("平均亏损", f"{m.avg_loss_pct:+.2f}%")

    st.subheader("回撤区间")
    if m.drawdown_periods:
        dd_df = pd.DataFrame(m.drawdown_periods)
        st.dataframe(dd_df, use_container_width=True, hide_index=True)
    else:
        st.info("没有显著回撤区间。")

with tab_detail:
    if trades:
        trades_df = pd.DataFrame(
            [
                {
                    "ID": t.id,
                    "方向": t.side,
                    "开仓时间": pd.to_datetime(t.entry_time, unit="ms"),
                    "开仓价": t.entry_price,
                    "平仓时间": pd.to_datetime(t.exit_time, unit="ms"),
                    "平仓价": t.exit_price,
                    "平仓原因": t.exit_reason,
                    "持仓(h)": round(t.hold_hours, 2),
                    "盈亏(%)": round(t.pnl_pct, 3),
                    "盈亏(USDT)": round(t.pnl_abs, 2),
                    "MAE(%)": round(t.mae_pct, 3),
                    "MFE(%)": round(t.mfe_pct, 3),
                }
                for t in trades
            ]
        )
        st.dataframe(trades_df, use_container_width=True, hide_index=True)
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "下载交易明细 CSV",
                trades_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"backtest_trades_{cfg['strategy_name']}_{symbol.replace('/', '_')}.csv",
                use_container_width=True,
            )
        with dl2:
            st.download_button(
                "下载文本报告",
                generate_report(result).encode("utf-8"),
                file_name=f"backtest_report_{cfg['strategy_name']}_{symbol.replace('/', '_')}.txt",
                use_container_width=True,
            )
    else:
        st.info("回测期间没有产生任何交易。")
