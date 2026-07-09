"""CryptoQuant Dashboard — home / overview page.

Usage:
    uv run streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

_DASHBOARD_DIR = Path(__file__).resolve().parent
for _p in (_DASHBOARD_DIR.parent, _DASHBOARD_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd
import streamlit as st

from utils import (
    discover_strategies,
    get_config,
    get_store,
    list_ohlcv_series,
    list_trade_journals,
    load_journal,
    strategy_name_from_journal_path,
)

st.set_page_config(page_title="CryptoQuant Dashboard", page_icon="📈", layout="wide")

st.title("📈 CryptoQuant Dashboard")
st.caption("加密货币量化交易系统 · 数据总览")

try:
    config = get_config()
except Exception as e:
    st.error(f"配置加载失败: {e}")
    st.stop()

col1, col2, col3, col4 = st.columns(4)

series = list_ohlcv_series()
col1.metric("行情数据表", len(series))

strategies = discover_strategies()
col2.metric("已发现策略", len(strategies))

journals = list_trade_journals()
col3.metric("交易日志文件", len(journals))

col4.metric("默认交易对 / 周期", f"{config.trading.default_quote} · {config.trading.default_timeframe}")

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("行情数据")
    if series:
        store = get_store()
        rows = []
        for exchange, symbol, timeframe in series:
            rng = store.get_range(exchange, symbol, timeframe)
            if rng is None:
                continue
            start, end = pd.to_datetime(rng[0], unit="ms"), pd.to_datetime(rng[1], unit="ms")
            rows.append(
                {
                    "交易所": exchange,
                    "交易对": symbol,
                    "周期": timeframe,
                    "起始时间": start,
                    "结束时间": end,
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("暂无本地行情数据，请到「行情数据」页面拉取。")

with right:
    st.subheader("策略与实盘/模拟状态")
    if strategies:
        st.dataframe(
            pd.DataFrame(
                {
                    "策略": list(strategies.keys()),
                    "周期": [getattr(s, "timeframe", "-") for s in strategies.values()],
                    "最小样本数": [getattr(s, "min_bars", "-") for s in strategies.values()],
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("未在 strategies/ 目录发现策略。")

    if journals:
        rows = []
        for path in journals:
            name = strategy_name_from_journal_path(path)
            stats = load_journal(name).stats()
            rows.append({"策略": name, "交易笔数": stats.get("total", 0), "胜率(%)": round(stats.get("win_rate", 0), 1)})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("暂无交易日志，请到「实盘监控」页面查看说明。")

st.divider()
st.caption("使用左侧导航切换：行情数据 · 回测结果 · 实盘监控 · 策略参数")
