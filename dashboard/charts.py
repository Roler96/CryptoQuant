"""Shared Plotly figure builders for the dashboard."""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from cryptoquant.engine.types import Trade

GREEN = "#26a69a"
RED = "#ef5350"
GREY = "#90a4ae"

_MARGIN = dict(l=10, r=10, t=40, b=10)


def equity_curve_fig(equity: pd.Series, title: str = "权益曲线") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=equity.index, y=equity.values, name="权益", line=dict(color=GREEN)))
    fig.update_layout(title=title, height=350, margin=_MARGIN)
    return fig


def drawdown_fig(drawdown: pd.Series, title: str = "回撤曲线") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown.values, name="回撤",
        fill="tozeroy", line=dict(color=RED),
    ))
    fig.update_layout(title=title, height=250, margin=_MARGIN)
    return fig


def monthly_returns_fig(monthly: pd.Series, title: str = "月度收益率 (%)") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[d.strftime("%Y-%m") for d in monthly.index], y=monthly.values,
        marker_color=[GREEN if v >= 0 else RED for v in monthly.values],
    ))
    fig.update_layout(title=title, height=280, margin=_MARGIN)
    return fig


def candlestick_fig(df: pd.DataFrame, title: str = "", with_volume: bool = True) -> go.Figure:
    if with_volume:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
            vertical_spacing=0.03, subplot_titles=(title, "成交量"),
        )
    else:
        fig = go.Figure()
        fig.update_layout(title=title)

    candle = go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color=GREEN, decreasing_line_color=RED, name="OHLC",
    )
    if with_volume:
        fig.add_trace(candle, row=1, col=1)
        colors = [GREEN if c >= o else RED for o, c in zip(df["open"], df["close"])]
        fig.add_trace(go.Bar(x=df.index, y=df["volume"], marker_color=colors, name="Volume"), row=2, col=1)
    else:
        fig.add_trace(candle)

    fig.update_layout(
        height=650 if with_volume else 500, xaxis_rangeslider_visible=False,
        showlegend=False, margin=_MARGIN,
    )
    return fig


def trades_on_price_fig(df: pd.DataFrame, trades: list[Trade], title: str = "开平仓位置") -> go.Figure:
    """Close-price line with entry/exit markers for each trade."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["close"], name="收盘价", line=dict(color=GREY, width=1)))

    entries_long = [t for t in trades if t.side == "long"]
    entries_short = [t for t in trades if t.side == "short"]
    if entries_long:
        fig.add_trace(go.Scatter(
            x=[pd.to_datetime(t.entry_time, unit="ms") for t in entries_long],
            y=[t.entry_price for t in entries_long],
            mode="markers", name="开多",
            marker=dict(color=GREEN, size=9, symbol="triangle-up"),
        ))
    if entries_short:
        fig.add_trace(go.Scatter(
            x=[pd.to_datetime(t.entry_time, unit="ms") for t in entries_short],
            y=[t.entry_price for t in entries_short],
            mode="markers", name="开空",
            marker=dict(color=RED, size=9, symbol="triangle-down"),
        ))

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    if wins:
        fig.add_trace(go.Scatter(
            x=[pd.to_datetime(t.exit_time, unit="ms") for t in wins],
            y=[t.exit_price for t in wins],
            mode="markers", name="平仓(盈利)",
            marker=dict(color=GREEN, size=7, symbol="circle", line=dict(color="white", width=1)),
        ))
    if losses:
        fig.add_trace(go.Scatter(
            x=[pd.to_datetime(t.exit_time, unit="ms") for t in losses],
            y=[t.exit_price for t in losses],
            mode="markers", name="平仓(亏损)",
            marker=dict(color=RED, size=7, symbol="x"),
        ))

    fig.update_layout(title=title, height=500, margin=_MARGIN)
    return fig


def pnl_histogram_fig(trades: list[Trade], bins: int = 30, title: str = "单笔盈亏分布 (%)") -> go.Figure:
    pnls = np.array([t.pnl_pct for t in trades])
    counts, edges = np.histogram(pnls, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=centers, y=counts, width=(edges[1] - edges[0]) * 0.9,
        marker_color=[GREEN if c >= 0 else RED for c in centers],
    ))
    fig.add_vline(x=0, line_dash="dash", line_color=GREY)
    fig.update_layout(title=title, height=350, margin=_MARGIN,
                      xaxis_title="盈亏 (%)", yaxis_title="笔数")
    return fig


def mae_mfe_scatter_fig(trades: list[Trade], title: str = "MAE vs 盈亏（止损位置诊断）") -> go.Figure:
    fig = go.Figure()
    for side, color in (("long", GREEN), ("short", RED)):
        subset = [t for t in trades if t.side == side]
        if not subset:
            continue
        fig.add_trace(go.Scatter(
            x=[t.mae_pct for t in subset], y=[t.pnl_pct for t in subset],
            mode="markers", name="多单" if side == "long" else "空单",
            marker=dict(color=color, size=6, opacity=0.6),
            customdata=[[t.id, t.mfe_pct] for t in subset],
            hovertemplate="ID %{customdata[0]}<br>MAE %{x:.2f}%<br>PnL %{y:.2f}%<br>MFE %{customdata[1]:.2f}%",
        ))
    fig.add_hline(y=0, line_dash="dash", line_color=GREY)
    fig.update_layout(title=title, height=400, margin=_MARGIN,
                      xaxis_title="最大不利偏移 MAE (%)", yaxis_title="最终盈亏 (%)")
    return fig


def exit_reason_fig(trades: list[Trade], title: str = "平仓原因分布") -> go.Figure:
    counter = Counter(t.exit_reason for t in trades)
    reasons = list(counter.keys())
    fig = go.Figure()
    fig.add_trace(go.Bar(x=reasons, y=[counter[r] for r in reasons], marker_color=GREY))
    fig.update_layout(title=title, height=300, margin=_MARGIN, yaxis_title="笔数")
    return fig
