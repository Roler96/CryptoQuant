"""Shared helpers for the Streamlit dashboard."""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pandas as pd
import streamlit as st

from cryptoquant.config import AppConfig, load_config
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.engine.types import BacktestResult
from cryptoquant.monitor.journal import TradeJournal
from cryptoquant.risk.sizer import ATRSizer, FixedSizer
from cryptoquant.strategy.base import Strategy

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
LOGS_DIR = PROJECT_ROOT / "logs"


def get_store() -> OHLCVStore:
    # Not cached: sqlite3 connections are bound to the thread that opened them,
    # and Streamlit may run script executions on different threads.
    config = get_config()
    return OHLCVStore(db_path=str(PROJECT_ROOT / config.data.db_path))


@st.cache_resource
def get_config() -> AppConfig:
    return load_config(PROJECT_ROOT / "config.yaml")


def parse_table_name(table: str) -> tuple[str, str, str] | None:
    """Reverse ``ohlcv_{exchange}_{symbol}_{timeframe}`` into its parts."""
    parts = table.split("_")
    if len(parts) < 4 or parts[0] != "ohlcv":
        return None
    exchange = parts[1]
    timeframe = parts[-1]
    symbol = "/".join(parts[2:-1])
    return exchange, symbol, timeframe


def list_ohlcv_series() -> list[tuple[str, str, str]]:
    """List (exchange, symbol, timeframe) tuples available in the OHLCV store."""
    store = get_store()
    series = [parse_table_name(t) for t in store.list_tables()]
    return sorted(s for s in series if s is not None)


@st.cache_resource
def discover_strategies() -> dict[str, type[Strategy]]:
    """Import every module under strategies/ and collect Strategy subclasses."""
    found: dict[str, type[Strategy]] = {}
    if not STRATEGIES_DIR.exists():
        return found

    for path in sorted(STRATEGIES_DIR.rglob("*.py")):
        if path.name == "__init__.py" or "__pycache__" in path.parts:
            continue
        module_name = f"_dashboard_strategy_{path.stem}_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Strategy) and obj is not Strategy and obj.__module__ == module_name:
                found[obj.__name__] = obj

    return found


def list_trade_journals() -> list[Path]:
    """List trade journal JSONL files under logs/."""
    if not LOGS_DIR.exists():
        return []
    return sorted(LOGS_DIR.glob("trade_journal_*.jsonl"))


def load_journal(strategy_name: str) -> TradeJournal:
    return TradeJournal(journal_dir=str(LOGS_DIR), strategy_name=strategy_name)


def strategy_name_from_journal_path(path: Path) -> str:
    return path.stem.removeprefix("trade_journal_")


def data_fingerprint(exchange: str, symbol: str, timeframe: str, df: pd.DataFrame) -> tuple:
    """Cheap cache key for an OHLCV frame without hashing every row."""
    last_ts = int(df.index[-1].timestamp()) if len(df) else 0
    return (exchange, symbol, timeframe, len(df), last_ts)


def make_sizer(sizer_items: tuple):
    """Build a position sizer from ((key, value), ...) config with a 'method' key."""
    cfg = dict(sizer_items)
    method = cfg.pop("method")
    if method == "fixed":
        return FixedSizer(risk_pct=cfg["risk_pct"], min_order=10.0)
    if method == "atr":
        return ATRSizer(
            base_risk_pct=cfg["base_risk_pct"],
            atr_period=int(cfg["atr_period"]),
            multiplier=cfg["multiplier"],
            min_order=10.0,
            max_pct=100.0,
        )
    return None  # engine default: full compounding


@st.cache_data(show_spinner=False, max_entries=20)
def run_backtest_cached(
    _df: pd.DataFrame,
    data_key: tuple,
    strategy_name: str,
    params_items: tuple,
    engine_kwargs_items: tuple,
    sizer_items: tuple,
) -> BacktestResult:
    """Run a backtest, cached on (data fingerprint, strategy, params, engine config).

    ``_df`` is excluded from hashing (leading underscore); ``data_key`` stands in
    for it so page interactions (tab switches, table sorts) don't re-run the engine.
    """
    strategy_cls = discover_strategies()[strategy_name]
    strategy = strategy_cls(params=dict(params_items))
    engine = BacktestEngine(
        sizer=make_sizer(sizer_items),
        **dict(engine_kwargs_items),
    )
    symbol = data_key[1]
    return engine.run(_df, strategy, symbol=symbol)
