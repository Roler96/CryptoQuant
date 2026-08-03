"""End-to-end orchestration for the frozen CRDR v1 protocol."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, cast

import pandas as pd

from cq.data.store import Store
from cq.research.crdr.backtest import BacktestResult, run_backtest
from cq.research.crdr.data import (
    ALL_INSTRUMENTS,
    END_MS,
    FACTOR_INSTRUMENT,
    START_MS,
    TRADE_INSTRUMENTS,
    DataContractError,
    StudyPanel,
    load_study_panel,
)
from cq.research.crdr.signals import SignalConfig, SignalEvent, generate_signals
from cq.research.crdr.stats import (
    EVALUATION_END,
    EVALUATION_START,
    block_bootstrap,
    calendar_segments,
    gate_verdict,
    performance,
)

STUDY_TAG = "crypto-cross-sectional-residual-dispersion-reversion-v1"
PROTOCOL_PATH = "docs/superpowers/specs/2026-08-03-intraday-crdr-design.md"
MAIN_CONFIG = SignalConfig()
NEIGHBORS = {
    "signal_4h": replace(MAIN_CONFIG, signal_hours=4),
    "signal_8h": replace(MAIN_CONFIG, signal_hours=8),
    "hold_4h": replace(MAIN_CONFIG, hold_hours=4),
    "hold_5h": replace(MAIN_CONFIG, hold_hours=5),
    "gate_q70": replace(MAIN_CONFIG, dispersion_quantile=0.70),
    "gate_q90": replace(MAIN_CONFIG, dispersion_quantile=0.90),
}


def run_study(store: Store, *, bootstrap_samples: int = 5_000) -> dict[str, Any]:
    """Run the preregistered main, stress, neighbors, ablations, and gates."""
    try:
        panel = load_study_panel(store)
    except DataContractError as exc:
        return _invalid_report(str(exc))

    main_events = generate_signals(panel, MAIN_CONFIG)
    main_result = _evaluation_result(run_backtest(panel, main_events, cost_bps=15))
    stress_result = _evaluation_result(
        run_backtest(
            panel,
            main_events,
            cost_bps=25,
            funding_penalty_bps=5,
        )
    )
    main_metrics = performance(main_result)
    stress_metrics = performance(stress_result)

    neighbor_metrics: dict[str, dict[str, float | int]] = {}
    for name, config in NEIGHBORS.items():
        events = generate_signals(panel, config)
        result = _evaluation_result(run_backtest(panel, events, cost_bps=15))
        neighbor_metrics[name] = performance(result)

    raw_events = generate_signals(panel, MAIN_CONFIG, residualized=False)
    ungated_events = generate_signals(panel, MAIN_CONFIG, gated=False)
    continuation_events = _continuation_events(main_events)
    ablation_results = {
        "raw_reversal": _evaluation_result(run_backtest(panel, raw_events, cost_bps=15)),
        "ungated_residual_reversal": _evaluation_result(
            run_backtest(panel, ungated_events, cost_bps=15)
        ),
        "residual_continuation": _evaluation_result(
            run_backtest(panel, continuation_events, cost_bps=15)
        ),
    }
    ablation_metrics = {
        name: performance(result) for name, result in ablation_results.items()
    }

    segments = calendar_segments(main_result)
    bootstrap = block_bootstrap(
        main_result.hourly_returns,
        samples=bootstrap_samples,
        seed=0,
    )
    gates = gate_verdict(
        integrity=True,
        main=main_metrics,
        stress=stress_metrics,
        segments=segments,
        neighbors=neighbor_metrics,
        bootstrap=bootstrap,
        ablations=ablation_metrics,
    )

    return {
        "study_tag": STUDY_TAG,
        "protocol": PROTOCOL_PATH,
        "data": _data_provenance(panel),
        "parameters": asdict(MAIN_CONFIG),
        "costs": {
            "main_bps_per_side": 15,
            "stress_bps_per_side": 25,
            "stress_funding_penalty_bps_per_episode": 5,
        },
        "main": main_metrics,
        "stress": stress_metrics,
        "bootstrap": bootstrap,
        "segments": segments,
        "neighbors": neighbor_metrics,
        "ablations": ablation_metrics,
        "gates": gates,
        "episodes": _serialize_episodes(main_events, main_result),
    }


def _evaluation_result(result: BacktestResult) -> BacktestResult:
    mask = (result.hourly_returns.index >= EVALUATION_START) & (
        result.hourly_returns.index < EVALUATION_END
    )
    hourly = result.hourly_returns.loc[mask]
    equity = (1.0 + hourly).cumprod().rename("equity")
    episodes = tuple(
        episode
        for episode in result.episodes
        if EVALUATION_START <= episode.entry_time < EVALUATION_END
    )
    return BacktestResult(hourly, equity, episodes)


def _continuation_events(events: list[SignalEvent]) -> list[SignalEvent]:
    return [
        replace(
            event,
            weights=tuple((instrument, -weight) for instrument, weight in event.weights),
        )
        for event in events
    ]


def _data_provenance(panel: StudyPanel) -> dict[str, Any]:
    return {
        "query_start": _iso_ms(START_MS),
        "end_exclusive": _iso_ms(END_MS),
        "evaluation_start": EVALUATION_START.isoformat(),
        "factor_instrument": FACTOR_INSTRUMENT,
        "trade_instruments": list(TRADE_INSTRUMENTS),
        "all_instruments": list(ALL_INSTRUMENTS),
        "fingerprints": panel.fingerprints,
        "raw_counts": panel.raw_counts,
        "dropped_counts": panel.dropped_counts,
    }


def _serialize_episodes(
    events: list[SignalEvent],
    result: BacktestResult,
) -> list[dict[str, Any]]:
    event_by_checkpoint = {event.checkpoint: event for event in events}
    serialized: list[dict[str, Any]] = []
    for episode in result.episodes:
        event = event_by_checkpoint[episode.checkpoint]
        serialized.append(
            {
                "checkpoint": episode.checkpoint.isoformat(),
                "entry_time": episode.entry_time.isoformat(),
                "exit_time": episode.exit_time.isoformat(),
                "dispersion": event.dispersion,
                "threshold": event.threshold,
                "residuals": dict(event.residuals),
                "weights": {
                    instrument: weight for instrument, weight in episode.weights if weight
                },
                "gross_return": episode.gross_return,
                "net_return": episode.net_return,
                "long_net_return": episode.long_net_return,
                "short_net_return": episode.short_net_return,
            }
        )
    return serialized


def _invalid_report(error: str) -> dict[str, Any]:
    return {
        "study_tag": STUDY_TAG,
        "protocol": PROTOCOL_PATH,
        "data": {
            "query_start": _iso_ms(START_MS),
            "end_exclusive": _iso_ms(END_MS),
        },
        "parameters": asdict(MAIN_CONFIG),
        "error": error,
        "gates": {"G0": False, "verdict": "INVALID"},
    }


def _iso_ms(timestamp_ms: int) -> str:
    timestamp = cast(pd.Timestamp, pd.Timestamp(timestamp_ms, unit="ms", tz="UTC"))
    return timestamp.isoformat()
