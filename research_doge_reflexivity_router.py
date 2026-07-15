"""Reproducible research audit for the DOGE spot reflexivity router.

The router combines two low-overlap, event-driven mechanisms:

* systemic attention handoff: an extreme BTC selloff while DOGE perpetual
  volume gains participation relative to DOGE spot volume;
* idiosyncratic liquidation exhaustion: an extreme beta-adjusted DOGE
  six-hour loss while that derivatives participation remains elevated for
  two consecutive closed bars.

Both mechanisms route into the same long-only DOGE/USDT spot position.  The
first event wins a portfolio-wide 48-hour signal cooldown; execution is at
the next hourly open and the position exits twelve hours later.

Usage:
    uv run python research_doge_reflexivity_router.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

import research_doge_attention_handoff as attention_research
from cryptoquant.utils import dataframe_fingerprint
from strategies.doge_reflexivity_router_spot import DogeReflexivityRouterSpot


FROZEN_FINGERPRINTS = {
    "doge_spot": "060a599e5c884689d4be1dd63c9d67fc9fa9048bccfdc53617ca8c1f4a17f853",
    "doge_swap": "5cf45705de469f7444930a2d38f89de4e7a5e09c995742704e68a52f1c3e0187",
    "btc_spot": "72316df119e21626e8563c3b0f9693058a0c5cf1b5af955bfa59b594272f2413",
}


@dataclass(frozen=True)
class RouteSignals:
    attention: pd.Series
    idiosyncratic: pd.Series
    union: pd.Series


def assert_frozen_snapshot(
    snapshot: attention_research.MarketSnapshot,
) -> None:
    """Stop a signed report from silently following mutable live candles."""
    actual = {
        "doge_spot": dataframe_fingerprint(snapshot.doge_spot),
        "doge_swap": dataframe_fingerprint(snapshot.doge_swap),
        "btc_spot": dataframe_fingerprint(snapshot.btc_spot),
    }
    if actual != FROZEN_FINGERPRINTS:
        raise RuntimeError(
            "Research snapshot drifted; re-audit before updating fingerprints: "
            f"expected={FROZEN_FINGERPRINTS}, actual={actual}"
        )


def build_signals(
    snapshot: attention_research.MarketSnapshot,
) -> RouteSignals:
    """Build the three frozen raw event streams and assert shipped parity."""
    strategy = DogeReflexivityRouterSpot()
    frame = attention_research.build_production_frame(snapshot)
    features = strategy.build_features(frame)
    signals = RouteSignals(
        attention=cast(pd.Series, features["raw_systemic_event"]).astype(int),
        idiosyncratic=cast(
            pd.Series, features["raw_idiosyncratic_event"]
        ).astype(int),
        union=cast(pd.Series, features["raw_event"]).astype(int),
    )
    spec = attention_research.SignalSpec()
    expected = attention_research.apply_cooldown(
        signals.union,
        spec,
        require_complete_trade=False,
    )
    actual = strategy.generate_signal(frame)
    pd.testing.assert_series_equal(actual, expected, check_names=False)
    return signals


def evaluation_table(
    snapshot: attention_research.MarketSnapshot,
    signals: RouteSignals,
) -> pd.DataFrame:
    """Compare both legs and the router on one signed accounting path."""
    spec = attention_research.SignalSpec()
    rows: list[dict[str, object]] = []
    streams = {
        "attention": signals.attention,
        "idiosyncratic": signals.idiosyncratic,
        "union_router": signals.union,
    }
    periods = (
        ("full", attention_research.DATA_START, attention_research.DATA_END),
        *attention_research.SEGMENTS,
    )
    for strategy_name, raw in streams.items():
        for period, start, end in periods:
            result = attention_research.evaluate(
                snapshot,
                raw,
                spec,
                start,
                end,
                label=f"{strategy_name}_{period}",
                position_pct=attention_research.DEPLOY_POSITION_PCT,
            )
            rows.append(
                {
                    "strategy": strategy_name,
                    "period": period,
                    **result.__dict__,
                }
            )
    return pd.DataFrame(rows)


def stress_table(
    snapshot: attention_research.MarketSnapshot,
    signals: RouteSignals,
) -> pd.DataFrame:
    """Run frozen cost and execution-delay stress for all three streams."""
    spec = attention_research.SignalSpec()
    rows: list[dict[str, object]] = []
    streams = {
        "attention": signals.attention,
        "idiosyncratic": signals.idiosyncratic,
        "union_router": signals.union,
    }
    for name, raw in streams.items():
        for slippage in (5.0, 15.0, 40.0):
            result = attention_research.evaluate(
                snapshot,
                raw,
                spec,
                attention_research.DATA_START,
                attention_research.DATA_END,
                label=name,
                position_pct=attention_research.DEPLOY_POSITION_PCT,
                slippage_bps=slippage,
            )
            rows.append(
                {
                    "strategy": name,
                    "stress": f"cost_{10 + slippage:.0f}bps_side",
                    **result.__dict__,
                }
            )
        for delay in (1, 2, 4):
            result = attention_research.evaluate(
                snapshot,
                raw,
                spec,
                attention_research.DATA_START,
                attention_research.DATA_END,
                label=name,
                position_pct=attention_research.DEPLOY_POSITION_PCT,
                delay_hours=delay,
            )
            rows.append(
                {
                    "strategy": name,
                    "stress": f"delay_{delay}h",
                    **result.__dict__,
                }
            )
    return pd.DataFrame(rows)


def yearly_table(
    snapshot: attention_research.MarketSnapshot,
    signals: RouteSignals,
) -> pd.DataFrame:
    """Return calendar-year deployment results without cold-start leakage."""
    spec = attention_research.SignalSpec()
    rows: list[dict[str, object]] = []
    for name, raw in {
        "attention": signals.attention,
        "idiosyncratic": signals.idiosyncratic,
        "union_router": signals.union,
    }.items():
        for year in range(2021, 2027):
            start = attention_research._timestamp(f"{year}-01-01")
            end = min(
                attention_research._timestamp(f"{year + 1}-01-01"),
                attention_research.DATA_END,
            )
            result = attention_research.evaluate(
                snapshot,
                raw,
                spec,
                start,
                end,
                label=f"{name}_{year}",
                position_pct=attention_research.DEPLOY_POSITION_PCT,
            )
            rows.append({"strategy": name, "year": year, **result.__dict__})
    return pd.DataFrame(rows)


def event_returns(
    snapshot: attention_research.MarketSnapshot,
    raw: pd.Series,
    *,
    commission_bps: float = 10.0,
    slippage_bps: float = 5.0,
) -> pd.DataFrame:
    """Return accepted event returns, exactly matching next-open costs."""
    spec = attention_research.SignalSpec()
    selected = attention_research.apply_cooldown(raw, spec)
    positions = np.flatnonzero(selected.to_numpy(dtype=int))
    rows: list[dict[str, object]] = []
    for position in positions:
        entry_position = position + 1
        exit_position = entry_position + spec.hold_hours
        entry_open = float(snapshot.doge_spot["open"].iloc[entry_position])
        exit_open = float(snapshot.doge_spot["open"].iloc[exit_position])
        entry_fill = entry_open * (1 + slippage_bps / 10_000)
        exit_fill = exit_open * (1 - slippage_bps / 10_000)
        ratio = exit_fill / entry_fill
        net_return = ratio - 1 - commission_bps / 10_000 * (1 + ratio)
        rows.append(
            {
                "signal": snapshot.doge_spot.index[position],
                "return": net_return,
            }
        )
    return pd.DataFrame(rows)


def _event_blocks(events: pd.DataFrame, max_gap_hours: int = 72) -> list[np.ndarray]:
    if events.empty:
        return []
    signals = cast(pd.Series, events["signal"])
    returns = cast(pd.Series, events["return"])
    blocks: list[list[float]] = [[float(returns.iloc[0])]]
    for position in range(1, len(events)):
        gap = signals.iloc[position] - signals.iloc[position - 1]
        if gap <= pd.Timedelta(hours=max_gap_hours):
            blocks[-1].append(float(returns.iloc[position]))
        else:
            blocks.append([float(returns.iloc[position])])
    return [np.asarray(block, dtype=float) for block in blocks]


def tail_and_block_audit(
    snapshot: attention_research.MarketSnapshot,
    signals: RouteSignals,
    *,
    simulations: int = 20_000,
    seed: int = 20_260_715,
) -> pd.DataFrame:
    """Delete right-tail trades and resample 72-hour event clusters."""
    rows: list[dict[str, object]] = []
    rng = np.random.default_rng(seed)
    for name, raw in {
        "attention": signals.attention,
        "idiosyncratic": signals.idiosyncratic,
        "union_router": signals.union,
    }.items():
        events = event_returns(snapshot, raw)
        if events.empty:
            rows.append(
                {
                    "strategy": name,
                    "trades": 0,
                    "blocks": 0,
                }
            )
            continue
        returns = cast(pd.Series, events["return"]).to_numpy(dtype=float)
        deploy_returns = returns * attention_research.DEPLOY_POSITION_PCT / 100
        deleted: dict[str, float] = {}
        for count in (0, 1, 3, 5, 10):
            keep_count = max(0, len(deploy_returns) - count)
            kept = np.sort(deploy_returns)[:keep_count]
            deleted[f"delete_{count}_return_pct"] = (
                float(np.prod(1 + kept) - 1) * 100 if len(kept) else 0.0
            )

        blocks = _event_blocks(events)
        block_deploy = [block * attention_research.DEPLOY_POSITION_PCT / 100 for block in blocks]
        block_compound = np.asarray(
            [np.prod(1 + block) - 1 for block in block_deploy],
            dtype=float,
        )
        samples = rng.integers(0, len(blocks), size=(simulations, len(blocks)))
        boot_returns = np.prod(1 + block_compound[samples], axis=1) - 1
        # Each resample keeps a fixed number of blocks, but block sizes vary;
        # concatenate their trade returns for an event-level mean interval.
        boot_means = np.empty(simulations, dtype=float)
        for row, choices in enumerate(samples):
            boot_means[row] = np.concatenate(
                [blocks[int(choice)] for choice in choices]
            ).mean()
        rows.append(
            {
                "strategy": name,
                "trades": len(events),
                "blocks": len(blocks),
                **deleted,
                "bootstrap_return_p5_pct": float(np.percentile(boot_returns, 5) * 100),
                "bootstrap_return_p50_pct": float(np.percentile(boot_returns, 50) * 100),
                "bootstrap_return_p95_pct": float(np.percentile(boot_returns, 95) * 100),
                "bootstrap_loss_probability_pct": float(np.mean(boot_returns < 0) * 100),
                "event_mean_ci_low_bps": float(np.percentile(boot_means, 2.5) * 10_000),
                "event_mean_ci_high_bps": float(np.percentile(boot_means, 97.5) * 10_000),
            }
        )
    return pd.DataFrame(rows)


def route_audit(signals: RouteSignals) -> dict[str, int]:
    """Count which raw mechanism won the union router's cooldown."""
    accepted = attention_research.apply_cooldown(
        signals.union,
        attention_research.SignalSpec(),
    ).astype(bool)
    attention = signals.attention.astype(bool)
    idiosyncratic = signals.idiosyncratic.astype(bool)
    return {
        "accepted": int(accepted.sum()),
        "attention_only": int((accepted & attention & ~idiosyncratic).sum()),
        "idiosyncratic_only": int((accepted & idiosyncratic & ~attention).sum()),
        "both": int((accepted & attention & idiosyncratic).sum()),
        "raw_exact_overlap": int((attention & idiosyncratic).sum()),
    }


def _print(frame: pd.DataFrame) -> None:
    print(frame.to_string(index=False, float_format=lambda value: f"{value:.3f}"))


def main() -> None:
    snapshot = attention_research.load_snapshot()
    assert_frozen_snapshot(snapshot)
    signals = build_signals(snapshot)
    attention_research.print_snapshot(snapshot)
    print("\nROUTE", route_audit(signals))
    print("\nMAIN AND SEGMENTS")
    _print(evaluation_table(snapshot, signals))
    print("\nCALENDAR YEARS")
    _print(yearly_table(snapshot, signals))
    print("\nCOST AND DELAY")
    _print(stress_table(snapshot, signals))
    print("\nTAIL AND EVENT-BLOCK BOOTSTRAP")
    _print(tail_and_block_audit(snapshot, signals))


if __name__ == "__main__":
    main()
