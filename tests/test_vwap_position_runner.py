import json

import numpy as np
import pandas as pd
import pytest

import scripts.vwap_position_study as vwap_position_study
from cq.research.split import ProtocolError
from scripts.vwap_position_study import fingerprint, main, run

BAR_MS = 300_000


def _synthetic_ohlcv(days: int, seed: int = 0) -> pd.DataFrame:
    """A small, strictly-positive, non-degenerate OHLCV series for smoke tests.

    Price and turnover follow `test_diagnose_coordinate_runner._synthetic_ohlcv`
    (log-random-walk close, lognormal volume), but `quote_volume` is *not*
    `volume * close` here. That simpler construction (used where only
    plumbing is exercised, e.g. the diagnose_coordinate smoke test) pins
    VWAP == close on every bar, which collapses this study's `v` and `c` into
    identical series -- an artefact this test must not have, since it exists
    to exercise `rank_partial(v, r_next | c)` on genuinely distinct series.
    Instead the average trade price is drawn uniformly inside [low, high]
    per `test_microstructure.test_centroid_delta_stays_in_unit_interval`,
    which decouples VWAP position from close position the way real order
    flow does.
    """
    n = days * 288
    rng = np.random.default_rng(seed)
    index = pd.to_datetime(np.arange(n) * BAR_MS, unit="ms", utc=True)
    log_price = np.cumsum(rng.normal(0.0, 0.0015, size=n))
    close = 100.0 * np.exp(log_price)
    open_ = np.concatenate(([close[0]], close[:-1]))
    wiggle = np.abs(rng.normal(0.0, 0.0008, size=n)) * close + 1e-6
    high = np.maximum(open_, close) + wiggle
    low = np.maximum(np.minimum(open_, close) - wiggle, 1e-3)
    volume = rng.lognormal(mean=10.0, sigma=1.0, size=n)
    average_trade_price = rng.uniform(low, high)
    quote_volume = average_trade_price * volume
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": quote_volume,
        },
        index=index,
    )


@pytest.fixture
def _shrunk_window(monkeypatch):
    """Shrink the explore window, draw count and expected fingerprint so
    `run()` finishes in seconds against synthetic data.

    `EXPECTED_FINGERPRINT` is monkeypatched to the synthetic frame's own
    fingerprint (computed below, once the frame exists) rather than disabled
    -- the check itself stays live and exercised, it is just pointed at data
    this test actually produced instead of the frozen real-data value.
    """
    days = 40
    monkeypatch.setattr(vwap_position_study, "EXPLORE_START", "2021-01-01")
    end = (pd.Timestamp("2021-01-01", tz="UTC") + pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    monkeypatch.setattr(vwap_position_study, "EXPLORE_END", end)
    monkeypatch.setattr(vwap_position_study, "DRAWS", 20)
    return days


def _patch_store_load(monkeypatch, frame: pd.DataFrame) -> None:
    def _fake_load_ohlcv(self, inst_id, timeframe, start_ms=None, end_ms=None):
        return frame

    monkeypatch.setattr(vwap_position_study.Store, "load_ohlcv", _fake_load_ohlcv)


def _patch_fingerprint(monkeypatch, frame: pd.DataFrame) -> None:
    monkeypatch.setattr(vwap_position_study, "EXPECTED_FINGERPRINT", fingerprint(frame))


VERDICTS = {"TRADEABLE-LEAD", "REAL-BUT-SUBTHRESHOLD", "ARTEFACT", "CLOSED", "INVALID"}


def test_run_end_to_end_smoke(monkeypatch, tmp_path, _shrunk_window):
    """`run()` on synthetic data: no real DB, just plumbing and structure.

    Mirrors `test_diagnose_coordinate_runner.test_run_end_to_end_smoke`: this
    does not check that a *value* is right (that would be flaky on random
    data), only that alignment holds and the whole pipeline produces a
    JSON-serialisable, structurally complete, protocol-shaped result.
    """
    days = _shrunk_window
    frame = _synthetic_ohlcv(days)
    _patch_store_load(monkeypatch, frame)
    _patch_fingerprint(monkeypatch, frame)

    out_path = tmp_path / "out.json"
    result = run(str(tmp_path / "smoke.db"), out_path)

    json.dumps(result, allow_nan=False)  # must not raise

    assert result["verdict"] in VERDICTS
    assert result["bars_aligned"] == result["bars"] - 1

    for key in (
        "window",
        "fingerprints",
        "versions",
        "fidelity",
        "clocks",
        "discriminant",
        "sanity",
        "gates",
    ):
        assert key in result

    for clock in ("dollar", "calendar"):
        payload = result["clocks"][clock]
        assert set(payload["scales"]) == set(vwap_position_study.SCALES)
        for scale in payload["scales"].values():
            assert 0.0 <= scale["p_value"] <= 1.0
            assert 0.0 <= scale["drop_fraction"] <= 1.0
            assert scale["n"] > 0

    for gate in (
        "g1_significance",
        "g2_sign_consistency",
        "g3_discriminant_sign_match",
        "g4_effect_size",
        "g4_scales_passed",
    ):
        assert gate in result["gates"]

    assert result["discriminant"]["classification"] in {
        "REAL_SIGNAL",
        "SPREAD_BOUNCE_ARTEFACT",
        "AMBIGUOUS",
        "NO_SIGNAL",
    }

    for key in ("spread_bounce_signature", "corr_v_c_calendar_5m", "fingerprint_ok", "all_passed"):
        assert key in result["sanity"]

    assert out_path.exists()
    on_disk = json.loads(out_path.read_text())
    assert on_disk == result


def test_run_raises_on_fingerprint_mismatch(monkeypatch, tmp_path, _shrunk_window):
    """A data fingerprint that does not match the frozen protocol value must
    hard-fail, not silently produce a report against different data."""
    days = _shrunk_window
    frame = _synthetic_ohlcv(days)
    _patch_store_load(monkeypatch, frame)
    monkeypatch.setattr(vwap_position_study, "EXPECTED_FINGERPRINT", "deadbeefdeadbeef")

    with pytest.raises(ProtocolError, match="fingerprint mismatch"):
        run(str(tmp_path / "smoke.db"), tmp_path / "out.json")


def test_gate_verdict_is_closed_when_g1_or_g2_fail():
    dollar = vwap_position_study.ClockAnalysis(
        per_scale={},
        m_by_scale={"15m": 0.01, "1h": -0.01, "4h": 0.01, "12h": -0.01},
        combined_p=0.9,
        combined_statistic=0.1,
        sign_agreement=2,
    )
    calendar = vwap_position_study.ClockAnalysis(
        per_scale={},
        m_by_scale={"15m": 0.01, "1h": -0.01, "4h": 0.01, "12h": -0.01},
        combined_p=0.9,
        combined_statistic=0.1,
        sign_agreement=2,
    )
    report = vwap_position_study._evaluate_gates(dollar, calendar, list(vwap_position_study.SCALES))
    assert not report.g1_passed
    assert report.verdict == "CLOSED"


def test_gate_verdict_is_artefact_when_g3_fails():
    dollar = vwap_position_study.ClockAnalysis(
        per_scale={},
        m_by_scale={"15m": 0.5, "1h": 0.5, "4h": 0.5, "12h": 0.5},
        combined_p=0.001,
        combined_statistic=5.0,
        sign_agreement=4,
    )
    calendar = vwap_position_study.ClockAnalysis(
        per_scale={},
        # opposite sign at 3/4 scales -> only 1/4 sign matches, below the 3/4 requirement
        m_by_scale={"15m": -0.5, "1h": -0.5, "4h": -0.5, "12h": 0.5},
        combined_p=0.001,
        combined_statistic=-5.0,
        sign_agreement=4,
    )
    report = vwap_position_study._evaluate_gates(dollar, calendar, list(vwap_position_study.SCALES))
    assert report.g1_passed and report.g2_passed
    assert not report.g3_passed
    assert report.verdict == "ARTEFACT"


def test_gate_verdict_is_subthreshold_when_g4_fails():
    # All M's below the tradeable lower bound at every scale, but significant
    # and sign-consistent both within the dollar clock and against calendar.
    small = {"15m": 0.01, "1h": 0.01, "4h": 0.005, "12h": 0.003}
    dollar = vwap_position_study.ClockAnalysis(
        per_scale={}, m_by_scale=small, combined_p=0.001, combined_statistic=5.0, sign_agreement=4
    )
    calendar = vwap_position_study.ClockAnalysis(
        per_scale={}, m_by_scale=small, combined_p=0.001, combined_statistic=5.0, sign_agreement=4
    )
    report = vwap_position_study._evaluate_gates(dollar, calendar, list(vwap_position_study.SCALES))
    assert report.g1_passed and report.g2_passed and report.g3_passed
    assert not report.g4_passed
    assert report.verdict == "REAL-BUT-SUBTHRESHOLD"


def test_gate_verdict_is_tradeable_lead_when_all_gates_pass():
    # Above every scale's tradeable lower bound (see TRADEABLE_LOWER_BOUND).
    big = {"15m": 0.10, "1h": 0.10, "4h": 0.05, "12h": 0.03}
    dollar = vwap_position_study.ClockAnalysis(
        per_scale={}, m_by_scale=big, combined_p=0.001, combined_statistic=5.0, sign_agreement=4
    )
    calendar = vwap_position_study.ClockAnalysis(
        per_scale={}, m_by_scale=big, combined_p=0.001, combined_statistic=5.0, sign_agreement=4
    )
    report = vwap_position_study._evaluate_gates(dollar, calendar, list(vwap_position_study.SCALES))
    assert report.g1_passed and report.g2_passed and report.g3_passed and report.g4_passed
    assert report.verdict == "TRADEABLE-LEAD"


def test_discriminant_table_all_four_rows():
    def clock(p, stat):
        return vwap_position_study.ClockAnalysis(
            per_scale={}, m_by_scale={}, combined_p=p, combined_statistic=stat, sign_agreement=0
        )

    # significant + significant + same sign -> REAL_SIGNAL
    assert (
        vwap_position_study._discriminant(clock(0.01, 1.0), clock(0.01, 1.0))["classification"]
        == "REAL_SIGNAL"
    )
    # not significant + significant -> SPREAD_BOUNCE_ARTEFACT (sign irrelevant)
    assert (
        vwap_position_study._discriminant(clock(0.5, 1.0), clock(0.01, -1.0))["classification"]
        == "SPREAD_BOUNCE_ARTEFACT"
    )
    # significant + (not significant or opposite sign) -> AMBIGUOUS
    assert (
        vwap_position_study._discriminant(clock(0.01, 1.0), clock(0.01, -1.0))["classification"]
        == "AMBIGUOUS"
    )
    assert (
        vwap_position_study._discriminant(clock(0.01, 1.0), clock(0.5, 1.0))["classification"]
        == "AMBIGUOUS"
    )
    # not significant + not significant -> NO_SIGNAL
    assert (
        vwap_position_study._discriminant(clock(0.5, 1.0), clock(0.5, -1.0))["classification"]
        == "NO_SIGNAL"
    )


def test_main_end_to_end_smoke(monkeypatch, tmp_path, capsys, _shrunk_window):
    """`main()` wires argv -> run() -> stdout + file; wiring is untested otherwise."""
    frame = _synthetic_ohlcv(_shrunk_window, seed=1)
    _patch_store_load(monkeypatch, frame)
    _patch_fingerprint(monkeypatch, frame)

    out_path = tmp_path / "main_out.json"
    exit_code = main(["--db", str(tmp_path / "smoke_main.db"), "--out", str(out_path)])

    assert exit_code == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["verdict"] in VERDICTS

    captured = capsys.readouterr()
    assert "verdict=" in captured.out
