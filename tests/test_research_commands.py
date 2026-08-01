"""CLI tests for research command registration and execution."""

from __future__ import annotations

import json

from cq.cli import build_parser


def test_research_bar_sequence_gbm_run_is_registered():
    parser = build_parser()
    args = parser.parse_args(["research", "bar-sequence-gbm", "run", "--out", "/tmp/does-not-matter.json"])

    assert args.handler is not None


def test_run_writes_the_report_json(tmp_path, monkeypatch):
    from cq.research import commands

    monkeypatch.setattr(
        commands,
        "run_study",
        lambda store: {"study_tag": "doge-bar-sequence-gbm-v1", "feature_sets": {}},
    )
    out_path = tmp_path / "report.json"

    args = build_parser().parse_args(
        ["research", "bar-sequence-gbm", "run", "--out", str(out_path), "--db", str(tmp_path / "cq.db")]
    )
    exit_code = args.handler(args)

    assert exit_code == 0
    written = json.loads(out_path.read_text())
    assert written["study_tag"] == "doge-bar-sequence-gbm-v1"
