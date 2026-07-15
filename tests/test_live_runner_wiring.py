"""Tests for strategy-specific live data and runtime contracts."""

from unittest.mock import MagicMock

import pytest

from cryptoquant.config import load_config
from cryptoquant.data.context_feed import ContextualClosedBarFeed
from cryptoquant.exceptions import StrategyError
from live_runner import build_strategy_data_feed, validate_strategy_runtime
from strategies.doge_attention_handoff_spot import DogeAttentionHandoffSpot


def test_attention_strategy_builds_spot_primary_and_two_context_feeds():
    strategy = DogeAttentionHandoffSpot()
    spot_fetcher = MagicMock()
    swap_fetcher = MagicMock()

    feed = build_strategy_data_feed(
        fetcher=spot_fetcher,
        store=MagicMock(),
        exchange="okx",
        symbol="DOGE/USDT",
        timeframe="1h",
        strategy=strategy,
        context_fetchers={"spot": spot_fetcher, "swap": swap_fetcher},
    )

    assert isinstance(feed, ContextualClosedBarFeed)
    assert feed.symbol == "DOGE/USDT"
    bindings = {market.alias: closed for market, closed in feed._contexts}
    assert bindings["swap"]._feed.fetcher is swap_fetcher
    assert bindings["swap"]._feed.storage_symbol == "DOGE-USDT-SWAP"
    assert bindings["btc"]._feed.fetcher is spot_fetcher
    assert bindings["btc"]._feed.storage_symbol == "BTC/USDT"


def test_attention_paper_profile_matches_frozen_runtime_contract():
    config = load_config("config.doge_attention_handoff.yaml", use_cache=False)

    validate_strategy_runtime(
        DogeAttentionHandoffSpot(),
        exchange=config.exchange.default,
        symbol=config.trading.symbol,
        account_type=config.trading.account_type,
        timeframe=config.trading.default_timeframe,
        trading_config=config.trading,
    )


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"symbol": "BTC/USDT"}, "symbol"),
        ({"account_type": "swap"}, "account_type"),
        ({"timeframe": "4h"}, "timeframe"),
    ],
)
def test_runtime_contract_rejects_wrong_market(override, match):
    config = load_config("config.doge_attention_handoff.yaml", use_cache=False)
    values = {
        "exchange": config.exchange.default,
        "symbol": config.trading.symbol,
        "account_type": config.trading.account_type,
        "timeframe": config.trading.default_timeframe,
    }
    values.update(override)

    with pytest.raises(StrategyError, match=match):
        validate_strategy_runtime(
            DogeAttentionHandoffSpot(),
            **values,
            trading_config=config.trading,
        )


def test_runtime_contract_rejects_exit_rule_drift():
    config = load_config("config.doge_attention_handoff.yaml", use_cache=False)
    config.trading.max_hold_hours = 24

    with pytest.raises(StrategyError, match="max_hold_hours"):
        validate_strategy_runtime(
            DogeAttentionHandoffSpot(),
            exchange=config.exchange.default,
            symbol=config.trading.symbol,
            account_type=config.trading.account_type,
            timeframe=config.trading.default_timeframe,
            trading_config=config.trading,
        )
