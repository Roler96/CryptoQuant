"""Deterministic client order identifiers for closed-bar intents."""

from cq.live.ids import MAX_CLIENT_ORDER_ID, client_order_id


def test_client_order_id_is_stable_numeric_and_inside_okx_limits():
    first = client_order_id("target", "DOGE-USDT", 123, 0.05, 0.06, 0.08)
    second = client_order_id("target", "DOGE-USDT", 123, 0.05, 0.06, 0.08)

    assert first == second
    assert first.isascii() and first.isdigit()
    assert len(first) <= 32
    assert 0 < int(first) <= MAX_CLIENT_ORDER_ID


def test_client_order_id_changes_with_role_bar_or_intent():
    base = client_order_id("target", "DOGE-USDT", 123, 0.05, 0.06, 0.08)

    assert client_order_id("protection", "DOGE-USDT", 123, 0.05, 0.06, 0.08) != base
    assert client_order_id("target", "DOGE-USDT", 124, 0.05, 0.06, 0.08) != base
    assert client_order_id("target", "DOGE-USDT", 123, 0.10, 0.06, 0.08) != base
