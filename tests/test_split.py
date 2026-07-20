"""Split protocol: fingerprints, the freeze point, and the holdout audit."""

import json

import pytest

from cq.research.split import (
    FORWARD_FREEZE,
    ProtocolError,
    Segment,
    SplitPlan,
    forward_holdout,
    holdout_access_count,
    record_holdout_access,
)


def plan(*segments, study="s"):
    return SplitPlan(study=study, segments=tuple(segments))


# ---- structure ---------------------------------------------------------


def test_overlapping_segments_are_rejected():
    # A bar in two segments is trained on and tested on at once.
    with pytest.raises(ProtocolError, match="overlap"):
        plan(
            Segment("train", "2021-01-01", "2024-07-01"),
            Segment("val", "2024-01-01", "2025-01-01"),
        )


def test_adjacent_segments_are_fine():
    plan(
        Segment("train", "2021-01-01", "2024-07-01"),
        Segment("val", "2024-07-01", "2025-07-01"),
    )


def test_duplicate_names_are_rejected():
    with pytest.raises(ProtocolError, match="duplicate"):
        plan(
            Segment("a", "2021-01-01", "2022-01-01"),
            Segment("a", "2022-01-01", "2023-01-01"),
        )


def test_a_segment_must_move_forwards():
    with pytest.raises(ProtocolError):
        Segment("bad", "2022-01-01", "2021-01-01")


def test_unknown_role_is_rejected():
    with pytest.raises(ProtocolError, match="unknown role"):
        Segment("x", "2021-01-01", "2022-01-01", role="magic")


def test_membership_is_half_open():
    segment = Segment("s", "2021-01-01", "2021-01-02")
    assert segment.contains(segment.start_ms)
    assert not segment.contains(segment.end_ms), "the end belongs to the next segment"


# ---- fingerprint -------------------------------------------------------


def test_the_same_plan_fingerprints_the_same_way():
    a = plan(Segment("train", "2021-01-01", "2024-07-01"))
    b = plan(Segment("train", "2021-01-01", "2024-07-01"))
    assert a.fingerprint == b.fingerprint


def test_moving_a_boundary_changes_the_fingerprint():
    # A study that quietly shifted its own split must show up as a different
    # study, not as a better result.
    a = plan(Segment("train", "2021-01-01", "2024-07-01"))
    b = plan(Segment("train", "2021-01-01", "2024-08-01"))
    assert a.fingerprint != b.fingerprint


def test_segment_order_does_not_change_the_fingerprint():
    first = Segment("train", "2021-01-01", "2024-07-01")
    second = Segment("val", "2024-07-01", "2025-07-01")
    assert plan(first, second).fingerprint == plan(second, first).fingerprint


def test_renaming_a_study_changes_the_fingerprint():
    segment = Segment("train", "2021-01-01", "2024-07-01")
    assert plan(segment, study="a").fingerprint != plan(segment, study="b").fingerprint


# ---- the freeze point --------------------------------------------------


def test_data_before_the_freeze_is_marked_as_already_seen():
    # Five and a half years of DOGE were searched over before this rebuild.
    segment = Segment("historic", "2021-01-01", "2026-01-01")
    assert segment.is_peeked


def test_data_after_the_freeze_is_not():
    segment = Segment("forward", FORWARD_FREEZE, "2027-01-01")
    assert not segment.is_peeked


def test_a_historical_only_plan_says_it_cannot_adjudicate():
    p = plan(
        Segment("train", "2021-01-01", "2024-07-01"),
        Segment("test", "2024-07-01", "2026-01-01", role="holdout"),
    )

    assert not p.has_genuine_holdout
    notes = " ".join(p.warnings())
    assert "cannot adjudicate" in notes
    assert "hypotheses, not evidence" in notes


def test_a_plan_reaching_past_the_freeze_has_a_real_holdout():
    p = plan(
        Segment("history", "2021-01-01", FORWARD_FREEZE),
        Segment("forward", FORWARD_FREEZE, "2027-01-01", role="holdout"),
    )
    assert p.has_genuine_holdout


def test_forward_holdout_refuses_before_any_data_has_accrued():
    # Expected early on: the clock starts at the freeze and cannot be hurried.
    with pytest.raises(ProtocolError, match="cannot be hurried"):
        forward_holdout("study", end=FORWARD_FREEZE)


def test_forward_holdout_covers_the_span_since_the_freeze():
    p = forward_holdout("study", end="2027-01-01")
    assert p.segment("forward").start == FORWARD_FREEZE
    assert p.has_genuine_holdout


def test_missing_segment_names_what_exists():
    p = plan(Segment("train", "2021-01-01", "2024-07-01"))
    with pytest.raises(KeyError, match="train"):
        p.segment("nope")


# ---- the holdout audit -------------------------------------------------


def test_a_holdout_read_is_recorded(tmp_path):
    log = tmp_path / "access.jsonl"
    record_holdout_access("study", "forward", "donchian 120/60 beats buy-and-hold", "abc", log)

    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["study"] == "study"
    assert entries[0]["hypothesis"] == "donchian 120/60 beats buy-and-hold"
    assert entries[0]["split_fingerprint"] == "abc"


def test_a_read_without_a_stated_hypothesis_is_refused(tmp_path):
    # Otherwise the hypothesis gets written after the result is known.
    with pytest.raises(ProtocolError, match="state the hypothesis"):
        record_holdout_access("study", "forward", "   ", "abc", tmp_path / "a.jsonl")


def test_reads_accumulate_because_the_count_is_the_correction(tmp_path):
    log = tmp_path / "access.jsonl"
    for i in range(3):
        record_holdout_access("study", "forward", f"hypothesis {i}", "abc", log)

    assert holdout_access_count("study", log) == 3


def test_counting_ignores_other_studies(tmp_path):
    log = tmp_path / "access.jsonl"
    record_holdout_access("mine", "forward", "h", "abc", log)
    record_holdout_access("theirs", "forward", "h", "abc", log)

    assert holdout_access_count("mine", log) == 1


def test_counting_a_study_that_never_looked_is_zero(tmp_path):
    assert holdout_access_count("study", tmp_path / "missing.jsonl") == 0
