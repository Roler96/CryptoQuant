"""Strategy catalogue — params and a live signal preview on price."""
import sys
from pathlib import Path

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
for _p in (_DASHBOARD_DIR.parent, _DASHBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import plotly.graph_objects as go
import streamlit as st

from utils import discover_strategies, get_config, get_store, list_ohlcv_series

st.set_page_config(page_title="策略参数 · CryptoQuant", page_icon="⚙️", layout="wide")
st.title("⚙️ 策略参数")

strategies = discover_strategies()
config = get_config()

if not strategies:
    st.warning("未在 strategies/ 目录发现任何策略。")
    st.stop()

st.caption(f"config.yaml 中当前配置的实盘策略: **{config.trading.strategy}**")

for name, cls in sorted(strategies.items()):
    with st.expander(f"{name}  ·  周期 {getattr(cls, 'timeframe', '-')}  ·  最小样本 {getattr(cls, 'min_bars', '-')}", expanded=False):
        if cls.__doc__:
            st.markdown(cls.__doc__.strip())
        params = getattr(cls, "DEFAULT_PARAMS", {})
        if params:
            st.table({"参数": list(params.keys()), "默认值": [str(v) for v in params.values()]})
        else:
            st.caption("该策略没有可配置参数。")

st.divider()
st.subheader("信号预览")

series = list_ohlcv_series()
if not series:
    st.info("本地没有行情数据，无法预览信号。请先到「行情数据」页面拉取。")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    strategy_name = st.selectbox("策略", sorted(strategies.keys()), key="preview_strategy")
with col2:
    series_labels = [f"{ex} · {sym} · {tf}" for ex, sym, tf in series]
    series_idx = st.selectbox("数据源", range(len(series)), format_func=lambda i: series_labels[i], key="preview_series")
    exchange, symbol, timeframe = series[series_idx]

store = get_store()
df = store.load(exchange, symbol, timeframe)

if df.empty:
    st.info("该数据源没有本地数据。")
    st.stop()

strategy_cls = strategies[strategy_name]
strategy = strategy_cls()

if len(df) < strategy.min_bars:
    st.warning(f"数据量不足：需要至少 {strategy.min_bars} 根K线，当前只有 {len(df)} 根。")
    st.stop()

try:
    signal = strategy.generate_signal(df)
except Exception as e:
    st.error(f"信号计算失败: {e}")
    st.stop()

df_view = df.tail(500)
signal_view = signal.reindex(df_view.index).fillna(0)

fig = go.Figure()
fig.add_trace(go.Scatter(x=df_view.index, y=df_view["close"], name="收盘价", line=dict(color="#90a4ae")))

longs = df_view.index[signal_view == 1]
shorts = df_view.index[signal_view == -1]
if len(longs):
    fig.add_trace(go.Scatter(
        x=longs, y=df_view.loc[longs, "close"], mode="markers", name="做多信号",
        marker=dict(color="#26a69a", size=8, symbol="triangle-up"),
    ))
if len(shorts):
    fig.add_trace(go.Scatter(
        x=shorts, y=df_view.loc[shorts, "close"], mode="markers", name="做空信号",
        marker=dict(color="#ef5350", size=8, symbol="triangle-down"),
    ))

fig.update_layout(title=f"{strategy_name} 信号预览 · {symbol} {timeframe}（最近500根）", height=500, margin=dict(l=10, r=10, t=40, b=10))
st.plotly_chart(fig, use_container_width=True)

st.caption(f"当前参数: {strategy.params}")
