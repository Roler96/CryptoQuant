"""OHLCV market data viewer — candlestick + volume."""
import sys
from pathlib import Path

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
for _p in (_DASHBOARD_DIR.parent, _DASHBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from cryptoquant.data.fetcher import OHLCVFetcher
from utils import get_config, get_store, list_ohlcv_series

st.set_page_config(page_title="行情数据 · CryptoQuant", page_icon="📊", layout="wide")
st.title("📊 行情数据")

config = get_config()
store = get_store()
series = list_ohlcv_series()

with st.sidebar:
    st.subheader("数据源选择")
    exchanges = sorted({s[0] for s in series}) or [config.exchange.default]
    exchange = st.selectbox("交易所", exchanges)

    symbols = sorted({s[1] for s in series if s[0] == exchange})
    symbol = st.selectbox("交易对", symbols, accept_new_options=True) if symbols else st.text_input("交易对", "BTC/USDT")

    ALL_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
    local_tfs = {s[2] for s in series if s[0] == exchange and s[1] == symbol}
    # Prefer a timeframe that has local data, else fall back to the config default
    preferred = min(local_tfs, key=ALL_TIMEFRAMES.index) if local_tfs else config.trading.default_timeframe
    tf_default_idx = ALL_TIMEFRAMES.index(preferred) if preferred in ALL_TIMEFRAMES else 4
    timeframe = st.selectbox(
        "周期",
        ALL_TIMEFRAMES,
        index=tf_default_idx,
        format_func=lambda tf: f"{tf}（已有本地数据）" if tf in local_tfs else tf,
    )

    n_bars = st.slider("显示最近 N 根K线", min_value=50, max_value=2000, value=300, step=50)

    st.divider()
    st.subheader("从交易所拉取新数据")
    fetch_days = st.number_input("拉取最近 N 天", min_value=1, max_value=365, value=7)
    fetch_clicked = st.button("拉取并保存到本地", use_container_width=True)

if msg := st.session_state.pop("fetch_msg", None):
    st.success(msg)

if fetch_clicked:
    with st.spinner(f"正在从 {exchange} 拉取 {symbol} {timeframe} 数据..."):
        try:
            end_ts = pd.Timestamp.now("UTC")
            start_ts = end_ts - pd.Timedelta(days=fetch_days)
            fetcher = OHLCVFetcher(exchange=exchange, testnet=False)
            df_new = fetcher.fetch_range(
                symbol, timeframe=timeframe,
                start=int(start_ts.timestamp() * 1000),
                end=int(end_ts.timestamp() * 1000),
            )
        except Exception as e:
            st.error(f"拉取失败: {e}")
            st.stop()

    if df_new.empty:
        st.warning("未获取到数据。")
    else:
        store.save(df_new, exchange, symbol, timeframe)
        st.session_state["fetch_msg"] = f"已保存 {len(df_new)} 根 {symbol} {timeframe} K线。"
        st.rerun()

df = store.load(exchange, symbol, timeframe)

if df.empty:
    st.info("本地没有该交易对/周期的数据，请在左侧拉取，或到「回测结果」页运行策略前先获取历史数据。")
    st.stop()

df = df.tail(n_bars)

c1, c2, c3, c4 = st.columns(4)
c1.metric("最新收盘价", f"{df['close'].iloc[-1]:,.4f}")
c2.metric("区间涨跌幅", f"{(df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100:+.2f}%")
c3.metric("区间最高", f"{df['high'].max():,.4f}")
c4.metric("区间最低", f"{df['low'].min():,.4f}")

fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
    vertical_spacing=0.03, subplot_titles=(f"{symbol} · {timeframe}", "成交量"),
)
fig.add_trace(
    go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350", name="OHLC",
    ),
    row=1, col=1,
)
volume_colors = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(df["open"], df["close"])]
fig.add_trace(go.Bar(x=df.index, y=df["volume"], marker_color=volume_colors, name="Volume"), row=2, col=1)
fig.update_layout(
    height=650, xaxis_rangeslider_visible=False, showlegend=False,
    margin=dict(l=10, r=10, t=40, b=10),
)
st.plotly_chart(fig, use_container_width=True)

with st.expander("原始数据"):
    st.dataframe(df, use_container_width=True)
