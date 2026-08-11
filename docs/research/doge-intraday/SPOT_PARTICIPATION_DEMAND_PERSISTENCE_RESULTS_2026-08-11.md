# SPDP v2 Discovery Results — 2026-08-11

- Verdict: `DISCOVERY_FAIL`
- Holdout accessed: `false`
- Continuous episodes: `60`
- Segment episodes: `{'2021': 18, '2022': 9, '2023': 12, '2024': 16, '2025-partial': 5}`

## Gates

- `G0_integrity`: `PASS`
- `G1_capacity`: `FAIL`
- `G2_main_economics`: `NOT_RUN`
- `G3_stress_outliers`: `NOT_RUN`
- `G4_calendar`: `NOT_RUN`
- `G5_bootstrap`: `NOT_RUN`
- `G6_neighborhood`: `NOT_RUN`
- `G7_mechanism`: `NOT_RUN`
- `G8_matched_random`: `NOT_RUN`

## Data

- Spot SHA-256: `11459117bfa9dcd09d942e9f0b4dfaf29c5e8bbb92272147cbbf8ba7bb28427f`
- Swap SHA-256: `1e0e3be7e9a88af2e9e36757eb0b697e1f8b81a54c98c04d5123d702c8d90f98`
- Bars per leg: `38688`
- Degenerate bars: spot `10`, swap `10`

## Audit metadata

- Worktree: `['## fable...origin/fable', '?? cq/research/spdp/', '?? cq/research/ura/', '?? docs/research/doge-intraday/', '?? tests/test_spdp_analysis.py', '?? tests/test_spdp_data.py', '?? tests/test_spdp_runner.py', '?? tests/test_spdp_signals.py', '?? tests/test_ura_analysis.py', '?? tests/test_ura_data.py', '?? tests/test_ura_strategy.py']`
- Tests: `uv run pytest -q tests/test_spdp_*.py` → `8 passed`
- Integration tests: SPDP + Context + event loop → `34 passed`
- Ruff: `All checks passed`
- Tool versions: `{'python': '3.11.15', 'numpy': '2.4.6', 'pytest': '8.4.2', 'uv': 'uv 0.11.8 (x86_64-unknown-linux-gnu)', 'ruff': 'ruff 0.15.22'}`
- Concentration: `NOT_RUN` (G1 FAIL)
